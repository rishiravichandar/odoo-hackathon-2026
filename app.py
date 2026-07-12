from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import sqlite3
import hashlib
import datetime
from database import get_db_connection, init_db, hash_password

app = Flask(__name__)
# Secure secret key for session management
app.secret_key = os.environ.get('SESSION_SECRET', 'transitops_secret_key_2026')

# Configure session cookies for iframe preview compatibility (SameSite=None, Secure=True)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_HTTPONLY=True
)

# Initialize the SQLite database automatically on startup
init_db()

# Middleware to restrict access to authenticated users only
@app.before_request
def require_login():
    # Allowed endpoints without login
    allowed_routes = ['login', 'quick_login', 'static']
    if request.endpoint not in allowed_routes and 'user_id' not in session:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template('login.html')

        hashed_pwd = hash_password(password)

        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE email = ? AND password = ?', 
            (email, hashed_pwd)
        ).fetchone()
        conn.close()

        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            session['user_role'] = user['role']
            flash(f'Welcome back, {user["name"]}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'error')

    return render_template('login.html')

@app.route('/quick-login')
def quick_login():
    role_param = request.args.get('role', 'manager')
    role_map = {
        'manager': 'Fleet Manager',
        'driver': 'Driver',
        'safety': 'Safety Officer',
        'finance': 'Financial Analyst'
    }
    target_role = role_map.get(role_param, 'Fleet Manager')

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE role = ? LIMIT 1', (target_role,)).fetchone()
    conn.close()

    if user:
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        session['user_email'] = user['email']
        session['user_role'] = user['role']
        flash(f'Logged in as {user["name"]} ({user["role"]})', 'success')
        return redirect(url_for('dashboard'))
    else:
        flash('Role user not found.', 'error')
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

def date_diff_days(d1_str, d2_str):
    try:
        t1 = datetime.datetime.strptime(d1_str[:10], '%Y-%m-%d')
        t2 = datetime.datetime.strptime(d2_str[:10], '%Y-%m-%d')
        return abs((t1 - t2).days)
    except Exception:
        return 99999

def update_overdue_maintenance(conn):
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    conn.execute('''
        UPDATE maintenance_logs 
        SET status = 'Overdue' 
        WHERE status = 'Scheduled' AND scheduled_date < ?
    ''', (today_str,))
    conn.commit()

def get_maintenance_alerts(conn):
    alerts = []
    
    # 1. Fetch all non-retired vehicles
    vehicles = conn.execute('SELECT * FROM vehicles WHERE status != "Retired"').fetchall()
    
    for veh in vehicles:
        # A. Mileage Threshold: 10,000 km since last completed service
        last_service = conn.execute('''
            SELECT * FROM maintenance_logs 
            WHERE vehicle_id = ? AND status = 'Completed' 
            ORDER BY completed_date DESC, id DESC LIMIT 1
        ''', (veh['id'],)).fetchone()
        
        if last_service:
            last_odo = last_service['current_odometer'] or 0
            km_since = veh['odometer'] - last_odo
            if km_since >= 10000:
                alerts.append({
                    'type': 'mileage',
                    'vehicle_id': veh['id'],
                    'registration_number': veh['registration_number'],
                    'vehicle_name': veh['name'],
                    'title': 'Service Interval Exceeded',
                    'message': f"Vehicle has driven {int(km_since):,} km since its last completed service (completed on {last_service['completed_date']}). Standard service interval is 10,000 km.",
                    'severity': 'danger'
                })
        else:
            # No completed service yet. Check if current odometer >= 10,000
            if veh['odometer'] >= 10000:
                alerts.append({
                    'type': 'mileage',
                    'vehicle_id': veh['id'],
                    'registration_number': veh['registration_number'],
                    'vehicle_name': veh['name'],
                    'title': 'First Service Due',
                    'message': f"Vehicle current odometer is {int(veh['odometer']):,} km and has no recorded maintenance logs. Standard service interval is 10,000 km.",
                    'severity': 'warning'
                })
                
        # B. Overdue Maintenance
        overdue_log = conn.execute('''
            SELECT * FROM maintenance_logs 
            WHERE vehicle_id = ? AND status = 'Overdue'
            ORDER BY scheduled_date ASC LIMIT 1
        ''', (veh['id'],)).fetchone()
        if overdue_log:
            alerts.append({
                'type': 'overdue',
                'vehicle_id': veh['id'],
                'maintenance_id': overdue_log['id'],
                'registration_number': veh['registration_number'],
                'vehicle_name': veh['name'],
                'title': 'Overdue Service Schedule',
                'message': f"Maintenance job MNT-{overdue_log['id']} ({overdue_log['maintenance_type']}) was scheduled on {overdue_log['scheduled_date']} but is currently Overdue.",
                'severity': 'danger'
            })
            
        # C. Repeated Maintenance within 30 days
        m_logs = conn.execute('''
            SELECT * FROM maintenance_logs 
            WHERE vehicle_id = ? AND status != 'Cancelled' 
            ORDER BY scheduled_date ASC
        ''', (veh['id'],)).fetchall()
        
        for i in range(len(m_logs) - 1):
            log1 = m_logs[i]
            log2 = m_logs[i+1]
            days = date_diff_days(log1['scheduled_date'], log2['scheduled_date'])
            if days <= 30:
                alerts.append({
                    'type': 'repeated',
                    'vehicle_id': veh['id'],
                    'registration_number': veh['registration_number'],
                    'vehicle_name': veh['name'],
                    'title': 'Repeated Service Window Warning',
                    'message': f"Frequent maintenance logs registered within 30 days: '{log1['maintenance_type']}' on {log1['scheduled_date']} and '{log2['maintenance_type']}' on {log2['scheduled_date']} ({days} days apart). Check for chronic issues.",
                    'severity': 'warning'
                })
                break
                
    return alerts

def get_fuel_alerts(conn):
    alerts = []
    # 1. High fuel expenditure (> 15000 INR)
    high_spent = conn.execute("""
        SELECT f.vehicle_id, v.registration_number, v.name, SUM(f.cost) as total_cost
        FROM fuel_logs f
        JOIN vehicles v ON f.vehicle_id = v.id
        GROUP BY f.vehicle_id
        HAVING total_cost > 15000
    """).fetchall()
    for h in high_spent:
        alerts.append({
            'type': 'expense',
            'vehicle_id': h['vehicle_id'],
            'registration_number': h['registration_number'],
            'vehicle_name': h['name'],
            'title': 'High Fuel Expenditure',
            'message': f"Cumulative fuel expenditure is high: ₹{h['total_cost']:,.2f}.",
            'severity': 'warning'
        })
        
    # 2. Bulk refills (> 100 liters in a single fill)
    bulk_refills = conn.execute("""
        SELECT f.*, v.registration_number, v.name
        FROM fuel_logs f
        JOIN vehicles v ON f.vehicle_id = v.id
        WHERE f.liters > 100
        ORDER BY f.date DESC
    """).fetchall()
    for b in bulk_refills:
        alerts.append({
            'type': 'consumption',
            'vehicle_id': b['vehicle_id'],
            'registration_number': b['registration_number'],
            'vehicle_name': b['name'],
            'title': 'Bulk Refill / High Volume',
            'message': f"Single fill of {b['liters']} Liters of {b['fuel_type']} on {b['date']}.",
            'severity': 'info'
        })
        
    # 3. Poor mileage (< 5.0 km/L)
    vehicles_all = conn.execute("SELECT id, registration_number, name FROM vehicles").fetchall()
    for veh in vehicles_all:
        veh_logs = conn.execute("SELECT * FROM fuel_logs WHERE vehicle_id = ? ORDER BY date ASC, id ASC", (veh['id'],)).fetchall()
        if len(veh_logs) > 1:
            v_mileages = []
            for idx in range(1, len(veh_logs)):
                dist = veh_logs[idx]['odometer'] - veh_logs[idx-1]['odometer']
                if dist > 0 and veh_logs[idx]['liters'] > 0:
                    v_mileages.append(dist / veh_logs[idx]['liters'])
            if v_mileages:
                avg_mil = sum(v_mileages) / len(v_mileages)
                if avg_mil < 5.0:
                    alerts.append({
                        'type': 'efficiency',
                        'vehicle_id': veh['id'],
                        'registration_number': veh['registration_number'],
                        'vehicle_name': veh['name'],
                        'title': 'Poor Fuel Mileage Alert',
                        'message': f"Average fuel efficiency is {avg_mil:.2f} km/L, which is below the target threshold of 5.0 km/L.",
                        'severity': 'danger'
                    })
    return alerts

@app.route('/')
def dashboard():
    # Fetch filter params
    selected_type = request.args.get('type', '')
    selected_status = request.args.get('status', '')
    selected_region = request.args.get('region', '')

    conn = get_db_connection()
    
    # Update overdue maintenance records automatically
    update_overdue_maintenance(conn)
    
    # Generate maintenance alerts
    alerts = get_maintenance_alerts(conn)
    
    # Generate fuel alerts
    fuel_alerts = get_fuel_alerts(conn)

    # 1. Fetch dynamic options for filters
    vehicle_types = [row['type'] for row in conn.execute('SELECT DISTINCT type FROM vehicles ORDER BY type').fetchall()]
    vehicle_statuses = [row['status'] for row in conn.execute('SELECT DISTINCT status FROM vehicles ORDER BY status').fetchall()]
    vehicle_regions = [row['region'] for row in conn.execute('SELECT DISTINCT region FROM vehicles ORDER BY region').fetchall()]

    # 2. Base query for filtered vehicles
    query = 'SELECT * FROM vehicles WHERE 1=1'
    params = []
    if selected_type:
        query += ' AND type = ?'
        params.append(selected_type)
    if selected_status:
        query += ' AND status = ?'
        params.append(selected_status)
    if selected_region:
        query += ' AND region = ?'
        params.append(selected_region)
    vehicles = conn.execute(query, params).fetchall()

    # 3. Compute live KPIs (from all unfiltered vehicles to maintain correct global context)
    total_vehicles = conn.execute('SELECT COUNT(*) FROM vehicles').fetchone()[0] or 0
    retired_vehicles = conn.execute('SELECT COUNT(*) FROM vehicles WHERE status = "Retired"').fetchone()[0] or 0
    active_vehicles = total_vehicles - retired_vehicles

    available_vehicles = conn.execute('SELECT COUNT(*) FROM vehicles WHERE status = "Available"').fetchone()[0] or 0
    in_maintenance = conn.execute('SELECT COUNT(*) FROM vehicles WHERE status IN ("In Shop", "Under Maintenance")').fetchone()[0] or 0
    on_trip_vehicles = conn.execute('SELECT COUNT(*) FROM vehicles WHERE status = "On Trip"').fetchone()[0] or 0

    total_drivers = conn.execute('SELECT COUNT(*) FROM drivers').fetchone()[0] or 0
    drivers_on_trip = conn.execute('SELECT COUNT(*) FROM drivers WHERE status = "On Trip"').fetchone()[0] or 0
    drivers_available = conn.execute('SELECT COUNT(*) FROM drivers WHERE status = "Available"').fetchone()[0] or 0
    drivers_on_leave = conn.execute('SELECT COUNT(*) FROM drivers WHERE status = "On Leave"').fetchone()[0] or 0
    drivers_inactive = conn.execute('SELECT COUNT(*) FROM drivers WHERE status = "Inactive"').fetchone()[0] or 0

    active_trips = conn.execute('SELECT COUNT(*) FROM trips WHERE status IN ("In Progress", "Dispatched")').fetchone()[0] or 0
    completed_trips = conn.execute('SELECT COUNT(*) FROM trips WHERE status = "Completed"').fetchone()[0] or 0
    cancelled_trips = conn.execute('SELECT COUNT(*) FROM trips WHERE status = "Cancelled"').fetchone()[0] or 0

    # Monthly spends for July 2026
    monthly_fuel_spend = conn.execute("SELECT SUM(cost) FROM fuel_logs WHERE date LIKE '2026-07%'").fetchone()[0] or 0.0
    monthly_maintenance_cost = conn.execute("SELECT SUM(actual_cost) FROM maintenance_logs WHERE status = 'Completed' AND completed_date LIKE '2026-07%'").fetchone()[0] or 0.0
    monthly_operating_expense = conn.execute("SELECT SUM(total_amount) FROM expenses WHERE status = 'Paid' AND date LIKE '2026-07%'").fetchone()[0] or 0.0

    # Calculate Fleet Utilization Ratio: (On Trip / Active Vehicles) * 100
    utilization_rate = 0.0
    if active_vehicles > 0:
        utilization_rate = (on_trip_vehicles / active_vehicles) * 100

    # Calculate fleet average fuel efficiency
    fleet_mileages = []
    all_logs_raw = conn.execute("SELECT * FROM fuel_logs ORDER BY date ASC, id ASC").fetchall()
    odo_tracker = {}
    for log in all_logs_raw:
        v_id = log['vehicle_id']
        current_odo = log['odometer']
        if v_id in odo_tracker:
            dist = current_odo - odo_tracker[v_id]
            if dist > 0 and log['liters'] > 0:
                fleet_mileages.append(dist / log['liters'])
        odo_tracker[v_id] = current_odo
    avg_fuel_efficiency = sum(fleet_mileages) / len(fleet_mileages) if fleet_mileages else 0.0

    total_distance_travelled = conn.execute("SELECT SUM(planned_distance) FROM trips WHERE status = 'Completed'").fetchone()[0] or 0.0

    kpis = {
        'total_vehicles': total_vehicles,
        'active_vehicles': active_vehicles,
        'available_vehicles': available_vehicles,
        'on_trip_vehicles': on_trip_vehicles,
        'in_maintenance': in_maintenance,
        'retired_vehicles': retired_vehicles,
        'total_drivers': total_drivers,
        'drivers_on_trip': drivers_on_trip,
        'drivers_available': drivers_available,
        'drivers_on_leave': drivers_on_leave,
        'drivers_inactive': drivers_inactive,
        'active_trips': active_trips,
        'completed_trips': completed_trips,
        'cancelled_trips': cancelled_trips,
        'monthly_fuel_spend': monthly_fuel_spend,
        'monthly_maintenance_cost': monthly_maintenance_cost,
        'monthly_operating_expense': monthly_operating_expense,
        'utilization_rate': utilization_rate,
        'avg_fuel_efficiency': avg_fuel_efficiency,
        'total_distance_travelled': total_distance_travelled
    }

    # 4. Fetch list of recent trips with joined Vehicle and Driver names
    trips_query = '''
        SELECT t.*, v.registration_number AS vehicle_name, d.name AS driver_name 
        FROM trips t 
        JOIN vehicles v ON t.vehicle_id = v.id 
        JOIN drivers d ON t.driver_id = d.id 
        ORDER BY t.created_at DESC
    '''
    trips = conn.execute(trips_query).fetchall()

    # 5. Charts and distributions data compilation
    import json
    
    # Vehicle status counts
    vehicle_status_distribution = {
        'Available': available_vehicles,
        'On Trip': on_trip_vehicles,
        'In Shop': in_maintenance,
        'Retired': retired_vehicles
    }
    
    # Driver status counts
    driver_status_distribution = {
        'Available': drivers_available,
        'On Trip': drivers_on_trip,
        'On Leave': drivers_on_leave,
        'Inactive': drivers_inactive
    }

    # Trip Status Distribution
    trip_statuses_raw = conn.execute("SELECT status, COUNT(*) as count FROM trips GROUP BY status").fetchall()
    trip_status_distribution = {row['status']: row['count'] for row in trip_statuses_raw}

    # Monthly Expenses trend
    monthly_expenses_raw = conn.execute("""
        SELECT strftime('%Y-%m', date) as month, SUM(total_amount) as total 
        FROM expenses 
        WHERE status = 'Paid' 
        GROUP BY month 
        ORDER BY month
    """).fetchall()
    monthly_expenses_trend = {row['month']: row['total'] for row in monthly_expenses_raw if row['month']}

    # Fuel vs Maintenance costs per month or cumulative
    total_fuel_cost = conn.execute("SELECT SUM(cost) FROM fuel_logs").fetchone()[0] or 0.0
    total_maintenance_cost = conn.execute("SELECT SUM(actual_cost) FROM maintenance_logs WHERE status = 'Completed'").fetchone()[0] or 0.0

    # Trips Per Month
    trips_per_month_raw = conn.execute("""
        SELECT strftime('%Y-%m', dispatch_date) as month, COUNT(*) as count 
        FROM trips 
        GROUP BY month 
        ORDER BY month
    """).fetchall()
    trips_per_month = {row['month']: row['count'] for row in trips_per_month_raw if row['month']}

    # Expense Categories
    expense_categories_raw = conn.execute("""
        SELECT type, SUM(total_amount) as total 
        FROM expenses 
        WHERE status = 'Paid' 
        GROUP BY type 
        ORDER BY total DESC
    """).fetchall()
    expense_categories = {row['type']: row['total'] for row in expense_categories_raw}

    # Maintenance Categories
    maint_categories_raw = conn.execute("""
        SELECT maintenance_type, COUNT(*) as count 
        FROM maintenance_logs 
        WHERE status = 'Completed' 
        GROUP BY maintenance_type 
        ORDER BY count DESC
    """).fetchall()
    maint_categories = {row['maintenance_type']: row['count'] for row in maint_categories_raw if row['maintenance_type']}

    # Fuel Consumption Trend
    fuel_trend_raw = conn.execute("""
        SELECT date(date) as day, SUM(liters) as liters 
        FROM fuel_logs 
        GROUP BY day 
        ORDER BY day ASC 
        LIMIT 30
    """).fetchall()
    fuel_consumption_trend = {row['day']: row['liters'] for row in fuel_trend_raw if row['day']}

    charts_data = {
        'vehicle_status_distribution': vehicle_status_distribution,
        'driver_status_distribution': driver_status_distribution,
        'trip_status_distribution': trip_status_distribution,
        'monthly_expenses_trend': monthly_expenses_trend,
        'fuel_vs_maintenance': {
            'Fuel': total_fuel_cost,
            'Maintenance': total_maintenance_cost
        },
        'trips_per_month': trips_per_month,
        'expense_categories': expense_categories,
        'maint_categories': maint_categories,
        'fuel_consumption_trend': fuel_consumption_trend
    }

    # 6. Fleet Analytics (Requirement 4)
    top_used_vehicles = conn.execute("""
        SELECT v.id, v.registration_number, v.name, COUNT(t.id) as trip_count, SUM(t.planned_distance) as total_dist
        FROM vehicles v
        JOIN trips t ON v.id = t.vehicle_id
        WHERE t.status = 'Completed'
        GROUP BY v.id
        ORDER BY trip_count DESC, total_dist DESC
        LIMIT 5
    """).fetchall()

    top_maint_vehicles = conn.execute("""
        SELECT v.id, v.registration_number, v.name, SUM(m.actual_cost) as total_cost
        FROM vehicles v
        JOIN maintenance_logs m ON v.id = m.vehicle_id
        WHERE m.status = 'Completed'
        GROUP BY v.id
        ORDER BY total_cost DESC
        LIMIT 5
    """).fetchall()

    top_fuel_vehicles = conn.execute("""
        SELECT v.id, v.registration_number, v.name, SUM(f.cost) as total_cost
        FROM vehicles v
        JOIN fuel_logs f ON v.id = f.vehicle_id
        GROUP BY v.id
        ORDER BY total_cost DESC
        LIMIT 5
    """).fetchall()

    most_efficient = conn.execute("""
        SELECT v.registration_number, v.name, SUM(t.planned_distance) / SUM(t.fuel_consumed) as efficiency
        FROM vehicles v
        JOIN trips t ON v.id = t.vehicle_id
        WHERE t.status = 'Completed' AND t.fuel_consumed > 0
        GROUP BY v.id
        ORDER BY efficiency DESC
        LIMIT 1
    """).fetchone()

    least_efficient = conn.execute("""
        SELECT v.registration_number, v.name, SUM(t.planned_distance) / SUM(t.fuel_consumed) as efficiency
        FROM vehicles v
        JOIN trips t ON v.id = t.vehicle_id
        WHERE t.status = 'Completed' AND t.fuel_consumed > 0
        GROUP BY v.id
        ORDER BY efficiency ASC
        LIMIT 1
    """).fetchone()

    downtime_report = conn.execute("""
        SELECT v.registration_number, v.name, m.description, m.start_date, m.status, m.estimated_duration
        FROM vehicles v
        JOIN maintenance_logs m ON v.id = m.vehicle_id
        WHERE v.status = 'In Shop' AND m.status != 'Completed'
    """).fetchall()

    # 7. Driver Analytics (Requirement 5)
    driver_analytics = conn.execute("""
        SELECT d.id, d.name, d.status, d.assigned_vehicle_id, d.safety_score, v.registration_number as vehicle_reg,
               COUNT(CASE WHEN t.status = 'Completed' THEN 1 END) as trips_completed,
               SUM(CASE WHEN t.status = 'Completed' THEN t.planned_distance ELSE 0 END) as distance_driven
        FROM drivers d
        LEFT JOIN vehicles v ON d.assigned_vehicle_id = v.id
        LEFT JOIN trips t ON d.id = t.driver_id
        GROUP BY d.id
        ORDER BY trips_completed DESC
    """).fetchall()

    # 8. Trip Analytics (Requirement 6)
    frequent_route_row = conn.execute("""
        SELECT source, destination, COUNT(*) as count 
        FROM trips 
        GROUP BY source, destination 
        ORDER BY count DESC 
        LIMIT 1
    """).fetchone()
    frequent_route = f"{frequent_route_row['source']} ➔ {frequent_route_row['destination']}" if frequent_route_row else "N/A"

    longest_trip_row = conn.execute("SELECT source, destination, planned_distance FROM trips ORDER BY planned_distance DESC LIMIT 1").fetchone()
    longest_trip = f"{longest_trip_row['source']} ➔ {longest_trip_row['destination']} ({longest_trip_row['planned_distance']:.0f} km)" if longest_trip_row else "N/A"

    shortest_trip_row = conn.execute("SELECT source, destination, planned_distance FROM trips WHERE status = 'Completed' ORDER BY planned_distance ASC LIMIT 1").fetchone()
    shortest_trip = f"{shortest_trip_row['source']} ➔ {shortest_trip_row['destination']} ({shortest_trip_row['planned_distance']:.0f} km)" if shortest_trip_row else "N/A"

    avg_trip_dist = conn.execute("SELECT AVG(planned_distance) FROM trips").fetchone()[0] or 0.0
    
    avg_trip_dur_row = conn.execute("""
        SELECT AVG((julianday(actual_return) - julianday(dispatch_date)) * 24) 
        FROM trips 
        WHERE status = 'Completed' AND actual_return IS NOT NULL AND dispatch_date IS NOT NULL
    """).fetchone()
    avg_trip_duration = avg_trip_dur_row[0] or 0.0

    completion_rate = 0.0
    total_trips = conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] or 0
    if total_trips > 0:
        completion_rate = (completed_trips / total_trips) * 100

    trip_analytics = {
        'frequent_route': frequent_route,
        'longest_trip': longest_trip,
        'shortest_trip': shortest_trip,
        'cancelled_trips': cancelled_trips,
        'completion_rate': completion_rate,
        'avg_trip_dist': avg_trip_dist,
        'avg_trip_duration': avg_trip_duration
    }

    # 9. Financial Analytics (Requirement 7)
    driver_salary_sum = conn.execute("SELECT SUM(total_amount) FROM expenses WHERE status = 'Paid' AND type = 'Driver Salary'").fetchone()[0] or 0.0
    misc_sum = conn.execute("SELECT SUM(total_amount) FROM expenses WHERE status = 'Paid' AND type NOT IN ('Fuel', 'Maintenance', 'Driver Salary')").fetchone()[0] or 0.0
    
    top_exp_cat_row = conn.execute("""
        SELECT type, SUM(total_amount) as total 
        FROM expenses 
        WHERE status = 'Paid' 
        GROUP BY type 
        ORDER BY total DESC 
        LIMIT 1
    """).fetchone()
    top_expense_cat = f"{top_exp_cat_row['type']} (₹{top_exp_cat_row['total']:,.2f})" if top_exp_cat_row else "N/A"

    cost_per_vehicle = conn.execute("""
        SELECT v.registration_number, SUM(e.total_amount) as total 
        FROM vehicles v 
        LEFT JOIN expenses e ON v.id = e.vehicle_id AND e.status = 'Paid' 
        GROUP BY v.id
    """).fetchall()

    operating_cost_per_km = 0.0
    all_expenses_sum = conn.execute("SELECT SUM(total_amount) FROM expenses WHERE status = 'Paid'").fetchone()[0] or 0.0
    if total_distance_travelled > 0:
        operating_cost_per_km = all_expenses_sum / total_distance_travelled

    financial_analytics = {
        'fuel_cost': total_fuel_cost,
        'maint_cost': total_maintenance_cost,
        'driver_salary': driver_salary_sum,
        'misc_cost': misc_sum,
        'top_expense_cat': top_expense_cat,
        'cost_per_vehicle': cost_per_vehicle,
        'operating_cost_per_km': operating_cost_per_km
    }

    conn.close()

    return render_template(
        'dashboard.html',
        active_page='dashboard',
        vehicles=vehicles,
        trips=trips,
        vehicle_types=vehicle_types,
        vehicle_statuses=vehicle_statuses,
        vehicle_regions=vehicle_regions,
        selected_type=selected_type,
        selected_status=selected_status,
        selected_region=selected_region,
        kpis=kpis,
        alerts=alerts,
        fuel_alerts=fuel_alerts,
        charts_data_json=json.dumps(charts_data),
        top_used_vehicles=top_used_vehicles,
        top_maint_vehicles=top_maint_vehicles,
        top_fuel_vehicles=top_fuel_vehicles,
        most_efficient=most_efficient,
        least_efficient=least_efficient,
        downtime_report=downtime_report,
        driver_analytics=driver_analytics,
        trip_analytics=trip_analytics,
        financial_analytics=financial_analytics
    )

# -----------------------------------------------------------------------------
# VEHICLE MANAGEMENT ROUTES
# -----------------------------------------------------------------------------
@app.route('/vehicles')
def vehicles_list():
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '')

    conn = get_db_connection()

    # 1. Base query with optional search and filter
    query = 'SELECT * FROM vehicles WHERE 1=1'
    params = []

    if status:
        if status == 'ALL_INCLUDING_RETIRED':
            pass  # Do not add status filter
        else:
            query += ' AND status = ?'
            params.append(status)
    else:
        # Hide Retired vehicles by default unless explicitly filtered
        query += ' AND status != "Retired"'

    if q:
        query += ' AND (registration_number LIKE ? OR name LIKE ?)'
        params.append(f'%{q}%')
        params.append(f'%{q}%')

    query += ' ORDER BY registration_number ASC'
    vehicles = conn.execute(query, params).fetchall()

    # 2. Compute specific Vehicle view KPIs
    total_fleet = conn.execute('SELECT COUNT(*) FROM vehicles').fetchone()[0]
    available_fleet = conn.execute('SELECT COUNT(*) FROM vehicles WHERE status = "Available"').fetchone()[0]
    on_trip_fleet = conn.execute('SELECT COUNT(*) FROM vehicles WHERE status = "On Trip"').fetchone()[0]
    in_shop_fleet = conn.execute('SELECT COUNT(*) FROM vehicles WHERE status = "In Shop"').fetchone()[0]

    vehicle_kpis = {
        'total': total_fleet,
        'available': available_fleet,
        'on_trip': on_trip_fleet,
        'in_shop': in_shop_fleet
    }

    conn.close()

    return render_template(
        'vehicles/list.html',
        active_page='vehicles',
        vehicles=vehicles,
        q=q,
        status=status,
        vehicle_kpis=vehicle_kpis
    )

@app.route('/vehicles/add', methods=['POST'])
def vehicles_add():
    registration_number = request.form.get('registration_number', '').strip().upper()
    name = request.form.get('name', '').strip()
    v_type = request.form.get('type', 'Van')
    region = request.form.get('region', 'North')
    
    try:
        max_load_capacity = float(request.form.get('max_load_capacity', 0))
        odometer = float(request.form.get('odometer', 0))
        acquisition_cost = float(request.form.get('acquisition_cost', 0))
    except ValueError:
        flash('Load capacity, odometer, and acquisition cost must be numeric values.', 'error')
        return redirect(url_for('vehicles_list'))

    status = request.form.get('status', 'Available')

    # Val 1: Unique Registration Number
    if not registration_number or not name:
        flash('Registration number and model name are required fields.', 'error')
        return redirect(url_for('vehicles_list'))

    # Val 2: Non-negative checks
    if max_load_capacity < 0 or odometer < 0 or acquisition_cost < 0:
        flash('Load capacity, odometer, and acquisition cost cannot be negative values.', 'error')
        return redirect(url_for('vehicles_list'))

    conn = get_db_connection()
    
    # Check registration number uniqueness
    existing = conn.execute('SELECT id FROM vehicles WHERE registration_number = ?', (registration_number,)).fetchone()
    if existing:
        conn.close()
        flash(f'Registration number "{registration_number}" already exists in the system.', 'error')
        return redirect(url_for('vehicles_list'))

    # Insert vehicle
    conn.execute('''
        INSERT INTO vehicles (registration_number, name, type, max_load_capacity, odometer, acquisition_cost, status, region)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (registration_number, name, v_type, max_load_capacity, odometer, acquisition_cost, status, region))
    
    conn.commit()
    conn.close()

    flash(f'Vehicle {registration_number} ({name}) registered successfully!', 'success')
    return redirect(url_for('vehicles_list'))

@app.route('/vehicles/edit/<int:id>', methods=['GET', 'POST'])
def vehicles_edit(id):
    conn = get_db_connection()
    vehicle = conn.execute('SELECT * FROM vehicles WHERE id = ?', (id,)).fetchone()
    
    if not vehicle:
        conn.close()
        flash('Vehicle not found.', 'error')
        return redirect(url_for('vehicles_list'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        v_type = request.form.get('type', 'Van')
        region = request.form.get('region', 'North')
        status = request.form.get('status', 'Available')

        try:
            max_load_capacity = float(request.form.get('max_load_capacity', 0))
            odometer = float(request.form.get('odometer', 0))
            acquisition_cost = float(request.form.get('acquisition_cost', 0))
        except ValueError:
            conn.close()
            flash('Capacity, odometer, and acquisition cost must be numeric values.', 'error')
            return redirect(url_for('vehicles_edit', id=id))

        # Validations
        if not name:
            conn.close()
            flash('Model name/descriptor is required.', 'error')
            return redirect(url_for('vehicles_edit', id=id))

        if max_load_capacity < 0 or odometer < 0 or acquisition_cost < 0:
            conn.close()
            flash('Capacity, odometer, and cost cannot be negative.', 'error')
            return redirect(url_for('vehicles_edit', id=id))

        # Update (excluding registration number/primary key)
        conn.execute('''
            UPDATE vehicles 
            SET name = ?, type = ?, max_load_capacity = ?, odometer = ?, acquisition_cost = ?, status = ?, region = ?
            WHERE id = ?
        ''', (name, v_type, max_load_capacity, odometer, acquisition_cost, status, region, id))
        
        conn.commit()
        conn.close()

        flash(f'Vehicle details updated successfully.', 'success')
        return redirect(url_for('vehicles_list'))

    conn.close()
    return render_template('vehicles/edit.html', active_page='vehicles', vehicle=vehicle)

@app.route('/vehicles/delete/<int:id>', methods=['POST'])
def vehicles_delete(id):
    conn = get_db_connection()
    vehicle = conn.execute('SELECT registration_number FROM vehicles WHERE id = ?', (id,)).fetchone()
    
    if not vehicle:
        conn.close()
        flash('Vehicle asset not found.', 'error')
        return redirect(url_for('vehicles_list'))

    # Soft Delete: Set status to 'Retired'
    conn.execute("UPDATE vehicles SET status = 'Retired' WHERE id = ?", (id,))
    conn.commit()
    conn.close()

    flash(f"Vehicle asset '{vehicle['registration_number']}' has been retired successfully.", 'warning')
    return redirect(url_for('vehicles_list'))

@app.route('/vehicles/<int:id>')
def vehicles_details(id):
    conn = get_db_connection()
    vehicle = conn.execute('SELECT * FROM vehicles WHERE id = ?', (id,)).fetchone()

    if not vehicle:
        conn.close()
        flash('Vehicle asset not found.', 'error')
        return redirect(url_for('vehicles_list'))

    # Retrieve real linked Maintenance history
    maintenance = conn.execute('''
        SELECT * FROM maintenance_logs 
        WHERE vehicle_id = ? 
        ORDER BY start_date DESC
    ''', (id,)).fetchall()

    # Retrieve real linked Fuel history
    fuel = conn.execute('''
        SELECT * FROM fuel_logs 
        WHERE vehicle_id = ? 
        ORDER BY date DESC
    ''', (id,)).fetchall()

    # Retrieve real linked Trip history
    trips = conn.execute('''
        SELECT t.*, d.name AS driver_name 
        FROM trips t
        JOIN drivers d ON t.driver_id = d.id
        WHERE t.vehicle_id = ? 
        ORDER BY t.created_at DESC
    ''', (id,)).fetchall()

    # Calculate real stats
    maintenance_cost_row = conn.execute('SELECT SUM(cost) FROM maintenance_logs WHERE vehicle_id = ?', (id,)).fetchone()
    maintenance_cost = maintenance_cost_row[0] if maintenance_cost_row[0] is not None else 0.0

    fuel_cost_row = conn.execute('SELECT SUM(cost) FROM fuel_logs WHERE vehicle_id = ?', (id,)).fetchone()
    fuel_cost = fuel_cost_row[0] if fuel_cost_row[0] is not None else 0.0

    other_expenses_row = conn.execute('SELECT SUM(amount) FROM expenses WHERE vehicle_id = ? AND type NOT IN ("Maintenance", "Fuel")', (id,)).fetchone()
    other_expenses = other_expenses_row[0] if other_expenses_row[0] is not None else 0.0

    total_expenses = maintenance_cost + fuel_cost + other_expenses

    conn.close()

    return render_template(
        'vehicles/details.html',
        active_page='vehicles',
        vehicle=vehicle,
        maintenance=maintenance,
        fuel=fuel,
        trips=trips,
        maintenance_cost=maintenance_cost,
        fuel_cost=fuel_cost,
        total_expenses=total_expenses
    )

# -----------------------------------------------------------------------------
# DRIVER MANAGEMENT ROUTES
# -----------------------------------------------------------------------------
@app.route('/drivers')
def drivers_list():
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    region = request.args.get('region', '')
    license_type = request.args.get('license_type', '')
    assigned = request.args.get('assigned', '')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    conn = get_db_connection()

    # Base query
    query = '''
        SELECT d.*, v.registration_number AS vehicle_reg 
        FROM drivers d
        LEFT JOIN vehicles v ON d.assigned_vehicle_id = v.id
        WHERE 1=1
    '''
    params = []

    # Filter status
    if status:
        if status == 'ALL_INCLUDING_INACTIVE':
            pass
        else:
            query += ' AND d.status = ?'
            params.append(status)
    else:
        # Hide Inactive by default
        query += ' AND d.status != "Inactive"'

    # Filter region
    if region:
        query += ' AND d.region = ?'
        params.append(region)

    # Filter license_type
    if license_type:
        query += ' AND d.license_category = ?'
        params.append(license_type)

    # Filter assigned
    if assigned:
        if assigned == 'assigned':
            query += ' AND d.assigned_vehicle_id IS NOT NULL'
        elif assigned == 'unassigned':
            query += ' AND d.assigned_vehicle_id IS NULL'

    # Search query
    if q:
        query += ' AND (d.name LIKE ? OR d.employee_id LIKE ? OR d.license_number LIKE ? OR d.contact_number LIKE ?)'
        pattern = f'%{q}%'
        params.extend([pattern, pattern, pattern, pattern])

    # Sort
    allowed_sorts = {
        'name': 'd.name',
        'date_joined': 'd.date_joined',
        'region': 'd.region',
        'status': 'd.status'
    }
    sort_field = allowed_sorts.get(sort_by, 'd.name')
    order = 'DESC' if sort_order == 'desc' else 'ASC'
    query += f' ORDER BY {sort_field} {order}'

    drivers = conn.execute(query, params).fetchall()

    # Driver view KPIs (global)
    total_drivers = conn.execute('SELECT COUNT(*) FROM drivers WHERE status != "Inactive"').fetchone()[0]
    available_drivers = conn.execute('SELECT COUNT(*) FROM drivers WHERE status = "Available"').fetchone()[0]
    on_trip_drivers = conn.execute('SELECT COUNT(*) FROM drivers WHERE status = "On Trip"').fetchone()[0]
    on_leave_drivers = conn.execute('SELECT COUNT(*) FROM drivers WHERE status = "On Leave"').fetchone()[0]

    driver_kpis = {
        'total': total_drivers,
        'available': available_drivers,
        'on_trip': on_trip_drivers,
        'on_leave': on_leave_drivers
    }

    # Fetch available vehicles for assignment dropdown in Add Driver or Details
    # (Available status and not assigned to another active driver)
    available_vehicles = conn.execute('''
        SELECT * FROM vehicles 
        WHERE status = "Available" 
        AND id NOT IN (
            SELECT assigned_vehicle_id FROM drivers 
            WHERE assigned_vehicle_id IS NOT NULL 
            AND status != "Inactive"
        )
    ''').fetchall()

    conn.close()

    return render_template(
        'drivers/list.html',
        active_page='drivers',
        drivers=drivers,
        q=q,
        status=status,
        region=region,
        license_type=license_type,
        assigned=assigned,
        sort_by=sort_by,
        sort_order=sort_order,
        driver_kpis=driver_kpis,
        available_vehicles=available_vehicles
    )

@app.route('/drivers/add', methods=['POST'])
def drivers_add():
    name = request.form.get('name', '').strip()
    employee_id = request.form.get('employee_id', '').strip().upper()
    license_number = request.form.get('license_number', '').strip().upper()
    license_category = request.form.get('license_type', 'LMV')
    license_expiry_date = request.form.get('license_expiry_date', '')
    contact_number = request.form.get('contact_number', '').strip()
    email = request.form.get('email', '').strip()
    address = request.form.get('address', '').strip()
    region = request.form.get('region', 'North')
    date_joined = request.form.get('date_joined', '')
    status = request.form.get('status', 'Available')
    assigned_vehicle_id_raw = request.form.get('assigned_vehicle_id', '')

    # Validations
    if not name or not employee_id or not license_number or not contact_number:
        flash('Full Name, Employee ID, License Number, and Phone Number are required fields.', 'error')
        return redirect(url_for('drivers_list'))

    # Phone number only digits validation
    # Strip any common chars like space, dash, plus for check, but store the clean digit string
    clean_phone = ''.join(c for c in contact_number if c.isdigit())
    if not clean_phone or len(clean_phone) < 4:
        flash('Phone number must contain only digits and be of a valid length.', 'error')
        return redirect(url_for('drivers_list'))

    # Email format validation
    if email and ('@' not in email or '.' not in email):
        flash('Please enter a valid email address.', 'error')
        return redirect(url_for('drivers_list'))

    conn = get_db_connection()

    # Check unique Employee ID
    existing_emp = conn.execute('SELECT id FROM drivers WHERE employee_id = ?', (employee_id,)).fetchone()
    if existing_emp:
        conn.close()
        flash(f'Employee ID "{employee_id}" is already assigned to another driver.', 'error')
        return redirect(url_for('drivers_list'))

    # Check unique License Number
    existing_lic = conn.execute('SELECT id FROM drivers WHERE license_number = ?', (license_number,)).fetchone()
    if existing_lic:
        conn.close()
        flash(f'License Number "{license_number}" is already registered.', 'error')
        return redirect(url_for('drivers_list'))

    assigned_vehicle_id = None
    if assigned_vehicle_id_raw:
        try:
            assigned_vehicle_id = int(assigned_vehicle_id_raw)
            # Verify vehicle is available and unassigned
            veh = conn.execute('''
                SELECT status FROM vehicles WHERE id = ?
            ''', (assigned_vehicle_id,)).fetchone()
            if not veh or veh['status'] != 'Available':
                conn.close()
                flash('Selected vehicle is not available for assignment.', 'error')
                return redirect(url_for('drivers_list'))
            # Check if assigned to another active driver
            other = conn.execute('''
                SELECT id FROM drivers WHERE assigned_vehicle_id = ? AND status != "Inactive"
            ''', (assigned_vehicle_id,)).fetchone()
            if other:
                conn.close()
                flash('Selected vehicle is already assigned to another active driver.', 'error')
                return redirect(url_for('drivers_list'))
        except ValueError:
            pass

    # Insert
    conn.execute('''
        INSERT INTO drivers (name, license_number, license_category, license_expiry_date, contact_number, status, employee_id, email, address, region, date_joined, assigned_vehicle_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, license_number, license_category, license_expiry_date or '2028-12-31', clean_phone, status, employee_id, email, address, region, date_joined or '2026-07-11', assigned_vehicle_id))

    conn.commit()
    conn.close()

    flash(f'Driver "{name}" registered successfully!', 'success')
    return redirect(url_for('drivers_list'))

@app.route('/drivers/edit/<int:id>', methods=['GET', 'POST'])
def drivers_edit(id):
    conn = get_db_connection()
    driver = conn.execute('SELECT * FROM drivers WHERE id = ?', (id,)).fetchone()

    if not driver:
        conn.close()
        flash('Driver not found.', 'error')
        return redirect(url_for('drivers_list'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        license_number = request.form.get('license_number', '').strip().upper()
        license_category = request.form.get('license_type', 'LMV')
        license_expiry_date = request.form.get('license_expiry_date', '')
        contact_number = request.form.get('contact_number', '').strip()
        email = request.form.get('email', '').strip()
        address = request.form.get('address', '').strip()
        region = request.form.get('region', 'North')
        date_joined = request.form.get('date_joined', '')
        status = request.form.get('status', 'Available')

        # Validations
        if not name or not license_number or not contact_number:
            conn.close()
            flash('Full Name, License Number, and Phone Number are required fields.', 'error')
            return redirect(url_for('drivers_edit', id=id))

        clean_phone = ''.join(c for c in contact_number if c.isdigit())
        if not clean_phone or len(clean_phone) < 4:
            conn.close()
            flash('Phone number must contain only digits.', 'error')
            return redirect(url_for('drivers_edit', id=id))

        if email and ('@' not in email or '.' not in email):
            conn.close()
            flash('Please enter a valid email address.', 'error')
            return redirect(url_for('drivers_edit', id=id))

        # Unique License Check
        existing_lic = conn.execute('SELECT id FROM drivers WHERE license_number = ? AND id != ?', (license_number, id)).fetchone()
        if existing_lic:
            conn.close()
            flash(f'License Number "{license_number}" is already registered to another driver.', 'error')
            return redirect(url_for('drivers_edit', id=id))

        # Business Rule: Inactive driver cannot have vehicle assigned
        assigned_vehicle_id = driver['assigned_vehicle_id']
        if status == 'Inactive':
            assigned_vehicle_id = None

        conn.execute('''
            UPDATE drivers 
            SET name = ?, license_number = ?, license_category = ?, license_expiry_date = ?, contact_number = ?, email = ?, address = ?, region = ?, date_joined = ?, status = ?, assigned_vehicle_id = ?
            WHERE id = ?
        ''', (name, license_number, license_category, license_expiry_date or '2028-12-31', clean_phone, email, address, region, date_joined or '2026-07-11', status, assigned_vehicle_id, id))

        conn.commit()
        conn.close()

        flash(f'Driver "{name}" details updated successfully.', 'success')
        return redirect(url_for('drivers_list'))

    conn.close()
    return render_template('drivers/edit.html', active_page='drivers', driver=driver)

@app.route('/drivers/<int:id>')
def drivers_details(id):
    conn = get_db_connection()
    driver = conn.execute('''
        SELECT d.*, v.registration_number AS vehicle_reg, v.name AS vehicle_name, v.status AS vehicle_status
        FROM drivers d
        LEFT JOIN vehicles v ON d.assigned_vehicle_id = v.id
        WHERE d.id = ?
    ''', (id,)).fetchone()

    if not driver:
        conn.close()
        flash('Driver not found.', 'error')
        return redirect(url_for('drivers_list'))

    # Recent trip count for the driver
    trip_count = conn.execute('SELECT COUNT(*) FROM trips WHERE driver_id = ?', (id,)).fetchone()[0]

    # Trip records for the driver
    trips = conn.execute('''
        SELECT t.*, v.registration_number AS vehicle_reg
        FROM trips t
        JOIN vehicles v ON t.vehicle_id = v.id
        WHERE t.driver_id = ?
        ORDER BY t.created_at DESC
    ''', (id,)).fetchall()

    # Dropdown for vehicle assignment: Available vehicles, and vehicles without another active driver
    available_vehicles = conn.execute('''
        SELECT * FROM vehicles 
        WHERE status = "Available" 
        AND id NOT IN (
            SELECT assigned_vehicle_id FROM drivers 
            WHERE assigned_vehicle_id IS NOT NULL 
            AND status != "Inactive" 
            AND id != ?
        )
    ''', (id,)).fetchall()

    conn.close()

    return render_template(
        'drivers/details.html',
        active_page='drivers',
        driver=driver,
        trip_count=trip_count,
        trips=trips,
        available_vehicles=available_vehicles
    )

@app.route('/drivers/delete/<int:id>', methods=['POST'])
def drivers_delete(id):
    conn = get_db_connection()
    driver = conn.execute('SELECT name FROM drivers WHERE id = ?', (id,)).fetchone()

    if not driver:
        conn.close()
        flash('Driver not found.', 'error')
        return redirect(url_for('drivers_list'))

    # Soft Delete: Set status to 'Inactive' and remove vehicle assignment
    conn.execute('UPDATE drivers SET status = "Inactive", assigned_vehicle_id = NULL WHERE id = ?', (id,))
    conn.commit()
    conn.close()

    flash(f'Driver "{driver["name"]}" has been deactivated successfully.', 'warning')
    return redirect(url_for('drivers_list'))

@app.route('/drivers/assign-vehicle/<int:id>', methods=['POST'])
def drivers_assign_vehicle(id):
    action = request.form.get('action', 'assign')
    vehicle_id_raw = request.form.get('vehicle_id', '')

    conn = get_db_connection()
    driver = conn.execute('SELECT * FROM drivers WHERE id = ?', (id,)).fetchone()

    if not driver:
        conn.close()
        flash('Driver not found.', 'error')
        return redirect(url_for('drivers_list'))

    if driver['status'] == 'Inactive':
        conn.close()
        flash('Cannot assign vehicles to inactive drivers.', 'error')
        return redirect(url_for('drivers_details', id=id))

    if action == 'remove':
        conn.execute('UPDATE drivers SET assigned_vehicle_id = NULL WHERE id = ?', (id,))
        conn.commit()
        conn.close()
        flash('Vehicle assignment removed successfully.', 'success')
        return redirect(url_for('drivers_details', id=id))

    # Assign / Change
    if not vehicle_id_raw:
        conn.close()
        flash('No vehicle selected for assignment.', 'error')
        return redirect(url_for('drivers_details', id=id))

    try:
        vehicle_id = int(vehicle_id_raw)
        
        # Verify vehicle status is Available
        veh = conn.execute('SELECT status, registration_number FROM vehicles WHERE id = ?', (vehicle_id,)).fetchone()
        if not veh:
            conn.close()
            flash('Selected vehicle does not exist.', 'error')
            return redirect(url_for('drivers_details', id=id))
            
        if veh['status'] != 'Available':
            conn.close()
            flash(f"Vehicle {veh['registration_number']} is in status '{veh['status']}' and cannot be assigned.", 'error')
            return redirect(url_for('drivers_details', id=id))

        # Check if another active driver already has this vehicle
        other = conn.execute('''
            SELECT name FROM drivers 
            WHERE assigned_vehicle_id = ? 
            AND status != "Inactive" 
            AND id != ?
        ''', (vehicle_id, id)).fetchone()
        
        if other:
            conn.close()
            flash(f"Vehicle {veh['registration_number']} is already active with driver {other['name']}.", 'error')
            return redirect(url_for('drivers_details', id=id))

        # Set assigned_vehicle_id
        conn.execute('UPDATE drivers SET assigned_vehicle_id = ? WHERE id = ?', (vehicle_id, id))
        conn.commit()
        conn.close()
        flash(f"Vehicle {veh['registration_number']} assigned successfully.", 'success')

    except ValueError:
        conn.close()
        flash('Invalid vehicle ID provided.', 'error')

    return redirect(url_for('drivers_details', id=id))

@app.route('/trips')
def trips_list():
    conn = get_db_connection()

    # Filters & Search
    selected_status = request.args.get('status', '').strip()
    selected_region = request.args.get('region', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    selected_driver_id = request.args.get('driver_id', '').strip()
    selected_vehicle_id = request.args.get('vehicle_id', '').strip()
    search_query = request.args.get('q', '').strip()
    sort_by = request.args.get('sort_by', 'dispatch_date').strip()

    # Build Query
    query = """
        SELECT t.*, 
               v.registration_number AS vehicle_reg, 
               v.name AS vehicle_name, 
               v.max_load_capacity AS vehicle_capacity,
               v.odometer AS vehicle_odometer,
               v.region AS vehicle_region,
               d.name AS driver_name, 
               d.employee_id AS driver_emp_id,
               d.contact_number AS driver_phone
        FROM trips t
        JOIN vehicles v ON t.vehicle_id = v.id
        JOIN drivers d ON t.driver_id = d.id
        WHERE 1=1
    """
    params = []

    if selected_status:
        query += " AND t.status = ?"
        params.append(selected_status)

    if selected_region:
        query += " AND v.region = ?"
        params.append(selected_region)

    if start_date:
        query += " AND DATE(t.dispatch_date) >= DATE(?)"
        params.append(start_date)

    if end_date:
        query += " AND DATE(t.dispatch_date) <= DATE(?)"
        params.append(end_date)

    if selected_driver_id:
        query += " AND t.driver_id = ?"
        params.append(int(selected_driver_id))

    if selected_vehicle_id:
        query += " AND t.vehicle_id = ?"
        params.append(int(selected_vehicle_id))

    if search_query:
        clean_q = search_query.lower()
        id_search = clean_q.replace('trip-', '').strip()
        query += """ AND (
            t.id = ? 
            OR LOWER(d.name) LIKE ? 
            OR LOWER(v.registration_number) LIKE ? 
            OR LOWER(t.source) LIKE ? 
            OR LOWER(t.destination) LIKE ?
        )"""
        params.extend([
            int(id_search) if id_search.isdigit() else -1,
            f"%{clean_q}%",
            f"%{clean_q}%",
            f"%{clean_q}%",
            f"%{clean_q}%"
        ])

    # Sorting Map
    valid_sort_cols = {
        'dispatch_date': 't.dispatch_date',
        'expected_return': 't.expected_return',
        'planned_distance': 't.planned_distance',
        'status': 't.status'
    }
    sort_col = valid_sort_cols.get(sort_by, 't.dispatch_date')
    query += f" ORDER BY {sort_col} DESC"

    # Execute
    trips = conn.execute(query, params).fetchall()

    # Dynamic KPI Calculations
    kpis = {
        'total': conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0],
        'in_progress': conn.execute("SELECT COUNT(*) FROM trips WHERE status = 'In Progress'").fetchone()[0],
        'scheduled': conn.execute("SELECT COUNT(*) FROM trips WHERE status = 'Scheduled'").fetchone()[0],
        'completed': conn.execute("SELECT COUNT(*) FROM trips WHERE status = 'Completed'").fetchone()[0],
        'cancelled': conn.execute("SELECT COUNT(*) FROM trips WHERE status = 'Cancelled'").fetchone()[0]
    }

    # Options for Create Form and Filters
    available_vehicles = conn.execute("SELECT * FROM vehicles WHERE status = 'Available' ORDER BY registration_number").fetchall()
    available_drivers = conn.execute("SELECT * FROM drivers WHERE status = 'Available' ORDER BY name").fetchall()
    all_drivers = conn.execute("SELECT id, name FROM drivers ORDER BY name").fetchall()
    all_vehicles = conn.execute("SELECT id, registration_number AS reg_num FROM vehicles ORDER BY registration_number").fetchall()
    all_regions = ['North', 'South', 'East', 'West', 'Central']

    conn.close()

    return render_template(
        'trips/list.html',
        active_page='trips',
        trips=trips,
        kpis=kpis,
        available_vehicles=available_vehicles,
        available_drivers=available_drivers,
        all_drivers=all_drivers,
        all_vehicles=all_vehicles,
        all_regions=all_regions,
        selected_status=selected_status,
        selected_region=selected_region,
        start_date=start_date,
        end_date=end_date,
        selected_driver_id=selected_driver_id,
        selected_vehicle_id=selected_vehicle_id,
        search_query=search_query,
        sort_by=sort_by
    )

@app.route('/trips/add', methods=['POST'])
def trips_add():
    vehicle_id = request.form.get('vehicle_id', '').strip()
    driver_id = request.form.get('driver_id', '').strip()
    source = request.form.get('source', '').strip()
    destination = request.form.get('destination', '').strip()
    purpose = request.form.get('purpose', '').strip()
    cargo_description = request.form.get('cargo_description', '').strip()
    cargo_weight = request.form.get('cargo_weight', '').strip()
    dispatch_date = request.form.get('dispatch_date', '').strip()
    expected_return = request.form.get('expected_return', '').strip()
    planned_distance = request.form.get('planned_distance', '').strip()
    notes = request.form.get('notes', '').strip()
    initial_status = request.form.get('status', 'Scheduled').strip()

    if not vehicle_id:
        flash('Vehicle selection is required.', 'error')
        return redirect(url_for('trips_list'))
    if not driver_id:
        flash('Driver selection is required.', 'error')
        return redirect(url_for('trips_list'))
    if not source or not destination:
        flash('Origin and Destination are required.', 'error')
        return redirect(url_for('trips_list'))
    if source.lower() == destination.lower():
        flash('Origin and Destination cannot be the same.', 'error')
        return redirect(url_for('trips_list'))

    try:
        cargo_weight = float(cargo_weight) if cargo_weight else 0.0
    except ValueError:
        flash('Cargo weight must be a valid number.', 'error')
        return redirect(url_for('trips_list'))

    try:
        planned_distance = float(planned_distance) if planned_distance else 0.0
    except ValueError:
        flash('Estimated distance must be a valid number.', 'error')
        return redirect(url_for('trips_list'))

    if dispatch_date and expected_return and dispatch_date > expected_return:
        flash('Dispatch date and time cannot be after the expected return date and time.', 'error')
        return redirect(url_for('trips_list'))

    conn = get_db_connection()
    
    # Fetch vehicle capacity and status
    vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    if not vehicle:
        conn.close()
        flash('Selected vehicle does not exist.', 'error')
        return redirect(url_for('trips_list'))
        
    if vehicle['status'] != 'Available':
        conn.close()
        flash(f"Vehicle {vehicle['registration_number']} is not Available (current status: {vehicle['status']}). Only Available vehicles can be assigned.", 'error')
        return redirect(url_for('trips_list'))

    if cargo_weight > vehicle['max_load_capacity']:
        conn.close()
        flash(f"Cargo weight ({cargo_weight} kg) exceeds vehicle maximum capacity ({vehicle['max_load_capacity']} kg).", 'error')
        return redirect(url_for('trips_list'))

    # Fetch driver status
    driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
    if not driver:
        conn.close()
        flash('Selected driver does not exist.', 'error')
        return redirect(url_for('trips_list'))

    if driver['status'] != 'Available':
        conn.close()
        flash(f"Driver {driver['name']} is not Available (current status: {driver['status']}). Only Available drivers can be assigned.", 'error')
        return redirect(url_for('trips_list'))

    # Save Trip
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trips (
            source, destination, vehicle_id, driver_id, cargo_weight, 
            planned_distance, status, dispatch_date, expected_return, 
            purpose, cargo_description, notes, revenue
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        source, destination, vehicle_id, driver_id, cargo_weight,
        planned_distance, initial_status, dispatch_date, expected_return,
        purpose, cargo_description, notes, 0.0
    ))
    trip_id = cursor.lastrowid

    # Apply business rules depending on starting status
    if initial_status == 'In Progress':
        cursor.execute("UPDATE drivers SET status = 'On Trip' WHERE id = ?", (driver_id,))
        cursor.execute("UPDATE vehicles SET status = 'On Trip' WHERE id = ?", (vehicle_id,))
        flash(f"Trip TRIP-{trip_id} created and dispatched successfully!", 'success')
    else:
        flash(f"Trip TRIP-{trip_id} scheduled successfully!", 'success')

    conn.commit()
    conn.close()
    return redirect(url_for('trips_list'))

@app.route('/trips/<int:id>')
def trips_details(id):
    conn = get_db_connection()
    trip = conn.execute("""
        SELECT t.*, 
               v.registration_number AS vehicle_reg, 
               v.name AS vehicle_name, 
               v.type AS vehicle_type,
               v.max_load_capacity AS vehicle_capacity,
               v.odometer AS vehicle_odometer,
               v.region AS vehicle_region,
               v.status AS vehicle_status,
               d.name AS driver_name, 
               d.employee_id AS driver_emp_id,
               d.contact_number AS driver_phone,
               d.email AS driver_email,
               d.safety_score AS driver_safety_score,
               d.status AS driver_status
        FROM trips t
        JOIN vehicles v ON t.vehicle_id = v.id
        JOIN drivers d ON t.driver_id = d.id
        WHERE t.id = ?
    """, (id,)).fetchone()

    if not trip:
        conn.close()
        flash('Trip not found.', 'error')
        return redirect(url_for('trips_list'))

    conn.close()
    return render_template('trips/details.html', active_page='trips', trip=trip)

@app.route('/trips/start/<int:id>', methods=['POST'])
def trips_start(id):
    conn = get_db_connection()
    trip = conn.execute("SELECT * FROM trips WHERE id = ?", (id,)).fetchone()
    if not trip:
        conn.close()
        flash('Trip not found.', 'error')
        return redirect(url_for('trips_list'))
    
    if trip['status'] != 'Scheduled':
        conn.close()
        flash('Only Scheduled trips can be started.', 'error')
        return redirect(url_for('trips_details', id=id))

    driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (trip['driver_id'],)).fetchone()
    vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (trip['vehicle_id'],)).fetchone()

    if driver['status'] != 'Available':
        conn.close()
        flash(f"Driver {driver['name']} is currently {driver['status']} and cannot be dispatched.", 'error')
        return redirect(url_for('trips_details', id=id))

    if vehicle['status'] != 'Available':
        conn.close()
        flash(f"Vehicle {vehicle['registration_number']} is currently {vehicle['status']} and cannot be dispatched.", 'error')
        return redirect(url_for('trips_details', id=id))

    cursor = conn.cursor()
    cursor.execute("UPDATE trips SET status = 'In Progress' WHERE id = ?", (id,))
    cursor.execute("UPDATE drivers SET status = 'On Trip' WHERE id = ?", (trip['driver_id'],))
    cursor.execute("UPDATE vehicles SET status = 'On Trip' WHERE id = ?", (trip['vehicle_id'],))
    conn.commit()
    conn.close()

    flash(f"Trip TRIP-{id} is now In Progress!", 'success')
    return redirect(url_for('trips_details', id=id))

@app.route('/trips/complete/<int:id>', methods=['POST'])
def trips_complete(id):
    actual_return = request.form.get('actual_return', '').strip()
    if not actual_return:
        actual_return = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    conn = get_db_connection()
    trip = conn.execute("SELECT * FROM trips WHERE id = ?", (id,)).fetchone()
    if not trip:
        conn.close()
        flash('Trip not found.', 'error')
        return redirect(url_for('trips_list'))

    if trip['status'] != 'In Progress':
        conn.close()
        flash('Only In Progress trips can be completed.', 'error')
        return redirect(url_for('trips_details', id=id))

    cursor = conn.cursor()
    cursor.execute("""
        UPDATE trips 
        SET status = 'Completed', actual_return = ? 
        WHERE id = ?
    """, (actual_return, id))
    
    cursor.execute("UPDATE drivers SET status = 'Available' WHERE id = ?", (trip['driver_id'],))
    cursor.execute("""
        UPDATE vehicles 
        SET status = 'Available', odometer = odometer + ? 
        WHERE id = ?
    """, (trip['planned_distance'], trip['vehicle_id']))

    conn.commit()
    conn.close()

    flash(f"Trip TRIP-{id} completed successfully! Vehicle odometer updated.", 'success')
    return redirect(url_for('trips_details', id=id))

@app.route('/trips/cancel/<int:id>', methods=['POST'])
def trips_cancel(id):
    conn = get_db_connection()
    trip = conn.execute("SELECT * FROM trips WHERE id = ?", (id,)).fetchone()
    if not trip:
        conn.close()
        flash('Trip not found.', 'error')
        return redirect(url_for('trips_list'))

    if trip['status'] in ['Completed', 'Cancelled']:
        conn.close()
        flash('Completed or Cancelled trips cannot be cancelled.', 'error')
        return redirect(url_for('trips_details', id=id))

    cursor = conn.cursor()
    cursor.execute("UPDATE trips SET status = 'Cancelled' WHERE id = ?", (id,))
    cursor.execute("UPDATE drivers SET status = 'Available' WHERE id = ?", (trip['driver_id'],))
    cursor.execute("UPDATE vehicles SET status = 'Available' WHERE id = ?", (trip['vehicle_id'],))

    conn.commit()
    conn.close()

    flash(f"Trip TRIP-{id} has been Cancelled. Assigned vehicle and driver are now Available.", 'info')
    return redirect(url_for('trips_details', id=id))

@app.route('/maintenance')
def maintenance_list():
    conn = get_db_connection()
    update_overdue_maintenance(conn)
    
    # Filters
    f_vehicle_id = request.args.get('vehicle_id', '')
    f_type = request.args.get('maintenance_type', '')
    f_status = request.args.get('status', '')
    f_service_center = request.args.get('service_center', '')
    f_date_from = request.args.get('date_from', '')
    f_date_to = request.args.get('date_to', '')
    
    q_search = request.args.get('q', '').strip()
    sort_by = request.args.get('sort_by', 'scheduled_date')
    sort_order = request.args.get('sort_order', 'DESC')
    
    sort_map = {
        'scheduled_date': 'm.scheduled_date',
        'cost': 'm.estimated_cost',
        'odometer': 'm.current_odometer'
    }
    sort_field = sort_map.get(sort_by, 'm.scheduled_date')
    if sort_order not in ['ASC', 'DESC']:
        sort_order = 'DESC'
        
    query = """
        SELECT m.*, v.registration_number AS vehicle_reg, v.name AS vehicle_name, v.type AS vehicle_type, v.odometer AS vehicle_odometer
        FROM maintenance_logs m
        JOIN vehicles v ON m.vehicle_id = v.id
        WHERE 1=1
    """
    params = []
    
    if f_vehicle_id:
        query += " AND m.vehicle_id = ?"
        params.append(f_vehicle_id)
    if f_type:
        query += " AND m.maintenance_type = ?"
        params.append(f_type)
    if f_status:
        query += " AND m.status = ?"
        params.append(f_status)
    if f_service_center:
        query += " AND m.service_center = ?"
        params.append(f_service_center)
    if f_date_from:
        query += " AND m.scheduled_date >= ?"
        params.append(f_date_from)
    if f_date_to:
        query += " AND m.scheduled_date <= ?"
        params.append(f_date_to)
        
    if q_search:
        query += " AND (v.registration_number LIKE ? OR m.technician_name LIKE ? OR m.notes LIKE ?)"
        term = f"%{q_search}%"
        params.extend([term, term, term])
        
    query += f" ORDER BY {sort_field} {sort_order}"
    
    logs = conn.execute(query, params).fetchall()
    
    vehicles_list = conn.execute("SELECT id, registration_number, name FROM vehicles WHERE status != 'Retired' ORDER BY registration_number").fetchall()
    types_list = [row['maintenance_type'] for row in conn.execute("SELECT DISTINCT maintenance_type FROM maintenance_logs WHERE maintenance_type IS NOT NULL AND maintenance_type != '' ORDER BY maintenance_type").fetchall()]
    std_types = ["Oil Change", "Brake Inspection", "Engine Service", "Tyre Replacement", "Battery Check", "General Service", "AC Service", "Suspension", "Electrical", "Other"]
    for t in std_types:
        if t not in types_list:
            types_list.append(t)
            
    statuses_list = ["Scheduled", "In Progress", "Completed", "Overdue", "Cancelled"]
    centers_list = [row['service_center'] for row in conn.execute("SELECT DISTINCT service_center FROM maintenance_logs WHERE service_center IS NOT NULL AND service_center != '' ORDER BY service_center").fetchall()]
    
    total_jobs = conn.execute("SELECT COUNT(*) FROM maintenance_logs").fetchone()[0]
    scheduled_count = conn.execute("SELECT COUNT(*) FROM maintenance_logs WHERE status = 'Scheduled'").fetchone()[0]
    in_progress_count = conn.execute("SELECT COUNT(*) FROM maintenance_logs WHERE status = 'In Progress'").fetchone()[0]
    completed_count = conn.execute("SELECT COUNT(*) FROM maintenance_logs WHERE status = 'Completed'").fetchone()[0]
    overdue_count = conn.execute("SELECT COUNT(*) FROM maintenance_logs WHERE status = 'Overdue'").fetchone()[0]
    total_cost = conn.execute("SELECT SUM(actual_cost) FROM maintenance_logs WHERE status = 'Completed'").fetchone()[0] or 0.0
    
    kpis = {
        'total_jobs': total_jobs,
        'scheduled': scheduled_count,
        'under_maintenance': in_progress_count,
        'completed': completed_count,
        'overdue': overdue_count,
        'total_cost': total_cost
    }
    
    alerts = get_maintenance_alerts(conn)
    conn.close()
    
    return render_template(
        'maintenance/list.html',
        active_page='maintenance',
        logs=logs,
        vehicles_list=vehicles_list,
        types_list=types_list,
        statuses_list=statuses_list,
        centers_list=centers_list,
        f_vehicle_id=f_vehicle_id,
        f_type=f_type,
        f_status=f_status,
        f_service_center=f_service_center,
        f_date_from=f_date_from,
        f_date_to=f_date_to,
        q_search=q_search,
        sort_by=sort_by,
        sort_order=sort_order,
        kpis=kpis,
        alerts=alerts
    )

@app.route('/maintenance/add', methods=['POST'])
def maintenance_add():
    vehicle_id = request.form.get('vehicle_id')
    maintenance_type = request.form.get('maintenance_type')
    service_center = request.form.get('service_center', '').strip()
    technician_name = request.form.get('technician_name', '').strip()
    scheduled_date = request.form.get('scheduled_date', '').strip()
    notes = request.form.get('notes', '').strip()
    
    try:
        estimated_cost = float(request.form.get('estimated_cost', 0))
        estimated_duration = int(request.form.get('estimated_duration', 1))
    except ValueError:
        flash('Invalid cost or duration format.', 'error')
        return redirect(url_for('maintenance_list'))
        
    if not vehicle_id or not maintenance_type or not service_center or not scheduled_date:
        flash('Please fill in all required fields.', 'error')
        return redirect(url_for('maintenance_list'))
        
    conn = get_db_connection()
    vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    if not vehicle:
        conn.close()
        flash('Vehicle not found.', 'error')
        return redirect(url_for('maintenance_list'))
        
    if vehicle['status'] == 'Retired':
        conn.close()
        flash('Cannot schedule maintenance for retired vehicles.', 'error')
        return redirect(url_for('maintenance_list'))
        
    if vehicle['status'] == 'On Trip':
        conn.close()
        flash('Vehicle is currently On Trip and cannot be scheduled for maintenance.', 'error')
        return redirect(url_for('maintenance_list'))
        
    active_m = conn.execute('''
        SELECT * FROM maintenance_logs 
        WHERE vehicle_id = ? AND status IN ('Scheduled', 'In Progress', 'Overdue')
    ''', (vehicle_id,)).fetchone()
    if active_m:
        conn.close()
        flash(f"Vehicle {vehicle['registration_number']} already has an active maintenance job (MNT-{active_m['id']}).", 'error')
        return redirect(url_for('maintenance_list'))
        
    if estimated_cost < 0:
        conn.close()
        flash('Estimated cost cannot be negative.', 'error')
        return redirect(url_for('maintenance_list'))
        
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    if scheduled_date < today_str:
        conn.close()
        flash('Scheduled date cannot be in the past.', 'error')
        return redirect(url_for('maintenance_list'))
        
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO maintenance_logs (
            vehicle_id, description, cost, start_date, end_date, status,
            maintenance_type, service_center, technician_name, scheduled_date,
            estimated_cost, estimated_duration, current_odometer, notes, actual_cost
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        vehicle_id, notes, 0.0, scheduled_date, None, 'Scheduled',
        maintenance_type, service_center, technician_name, scheduled_date,
        estimated_cost, estimated_duration, vehicle['odometer'], notes, 0.0
    ))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    
    flash(f"Maintenance job MNT-{new_id} scheduled successfully for vehicle {vehicle['registration_number']}.", 'success')
    return redirect(url_for('maintenance_list'))

@app.route('/maintenance/<int:id>')
def maintenance_details(id):
    conn = get_db_connection()
    log = conn.execute('''
        SELECT m.*, v.registration_number AS vehicle_reg, v.name AS vehicle_name, v.type AS vehicle_type, v.odometer AS vehicle_odometer, v.status AS vehicle_status
        FROM maintenance_logs m
        JOIN vehicles v ON m.vehicle_id = v.id
        WHERE m.id = ?
    ''', (id,)).fetchone()
    if not log:
        conn.close()
        flash('Maintenance record not found.', 'error')
        return redirect(url_for('maintenance_list'))
        
    history = conn.execute('''
        SELECT * FROM maintenance_logs 
        WHERE vehicle_id = ? AND id != ?
        ORDER BY scheduled_date DESC
    ''', (log['vehicle_id'], id)).fetchall()
    
    conn.close()
    return render_template('maintenance/details.html', active_page='maintenance', log=log, history=history)

@app.route('/maintenance/edit/<int:id>', methods=['GET', 'POST'])
def maintenance_edit(id):
    conn = get_db_connection()
    log = conn.execute('''
        SELECT m.*, v.registration_number AS vehicle_reg, v.name AS vehicle_name
        FROM maintenance_logs m
        JOIN vehicles v ON m.vehicle_id = v.id
        WHERE m.id = ?
    ''', (id,)).fetchone()
    if not log:
        conn.close()
        flash('Maintenance record not found.', 'error')
        return redirect(url_for('maintenance_list'))
        
    if log['status'] not in ['Scheduled', 'Overdue']:
        conn.close()
        flash('Only Scheduled or Overdue maintenance jobs can be edited.', 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    if request.method == 'POST':
        maintenance_type = request.form.get('maintenance_type')
        service_center = request.form.get('service_center', '').strip()
        technician_name = request.form.get('technician_name', '').strip()
        scheduled_date = request.form.get('scheduled_date', '').strip()
        notes = request.form.get('notes', '').strip()
        
        try:
            estimated_cost = float(request.form.get('estimated_cost', 0))
            estimated_duration = int(request.form.get('estimated_duration', 1))
        except ValueError:
            flash('Invalid cost or duration format.', 'error')
            return redirect(url_for('maintenance_edit', id=id))
            
        if not maintenance_type or not service_center or not scheduled_date:
            flash('Please fill in all required fields.', 'error')
            return redirect(url_for('maintenance_edit', id=id))
            
        if estimated_cost < 0:
            flash('Estimated cost cannot be negative.', 'error')
            return redirect(url_for('maintenance_edit', id=id))
            
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        if scheduled_date < today_str:
            flash('Scheduled date cannot be in the past.', 'error')
            return redirect(url_for('maintenance_edit', id=id))
            
        conn.execute('''
            UPDATE maintenance_logs 
            SET maintenance_type = ?, service_center = ?, technician_name = ?,
                scheduled_date = ?, start_date = ?, estimated_cost = ?,
                estimated_duration = ?, notes = ?, description = ?
            WHERE id = ?
        ''', (
            maintenance_type, service_center, technician_name,
            scheduled_date, scheduled_date, estimated_cost,
            estimated_duration, notes, notes, id
        ))
        conn.commit()
        conn.close()
        
        flash(f"Maintenance job MNT-{id} updated successfully.", 'success')
        return redirect(url_for('maintenance_details', id=id))
        
    conn.close()
    return render_template('maintenance/edit.html', active_page='maintenance', log=log)

@app.route('/maintenance/start/<int:id>', methods=['POST'])
def maintenance_start(id):
    conn = get_db_connection()
    log = conn.execute("SELECT * FROM maintenance_logs WHERE id = ?", (id,)).fetchone()
    if not log:
        conn.close()
        flash('Maintenance record not found.', 'error')
        return redirect(url_for('maintenance_list'))
        
    if log['status'] not in ['Scheduled', 'Overdue']:
        conn.close()
        flash('Only Scheduled or Overdue maintenance jobs can be started.', 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (log['vehicle_id'],)).fetchone()
    if vehicle['status'] == 'On Trip':
        conn.close()
        flash('Vehicle is currently On Trip and cannot enter maintenance.', 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    cursor = conn.cursor()
    cursor.execute("UPDATE maintenance_logs SET status = 'In Progress' WHERE id = ?", (id,))
    cursor.execute("UPDATE vehicles SET status = 'In Shop' WHERE id = ?", (log['vehicle_id'],))
    
    conn.commit()
    conn.close()
    
    flash(f"Maintenance job MNT-{id} started successfully. Vehicle status updated to 'In Shop'.", 'success')
    return redirect(url_for('maintenance_details', id=id))

@app.route('/maintenance/complete/<int:id>', methods=['POST'])
def maintenance_complete(id):
    completed_date = request.form.get('completed_date', '').strip()
    work_performed = request.form.get('work_performed', '').strip()
    parts_replaced = request.form.get('parts_replaced', '').strip()
    remarks = request.form.get('remarks', '').strip()
    
    try:
        actual_cost = float(request.form.get('actual_cost', 0))
        new_odometer = float(request.form.get('new_odometer', 0))
    except ValueError:
        flash('Invalid cost or odometer format.', 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    if not completed_date or not work_performed:
        flash('Completed date and work performed are required fields.', 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    if actual_cost < 0:
        flash('Actual cost cannot be negative.', 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    conn = get_db_connection()
    log = conn.execute("SELECT * FROM maintenance_logs WHERE id = ?", (id,)).fetchone()
    if not log:
        conn.close()
        flash('Maintenance record not found.', 'error')
        return redirect(url_for('maintenance_list'))
        
    if log['status'] != 'In Progress':
        conn.close()
        flash('Only In Progress maintenance jobs can be completed.', 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (log['vehicle_id'],)).fetchone()
    
    if new_odometer < vehicle['odometer']:
        conn.close()
        flash(f"Odometer cannot be less than current odometer ({vehicle['odometer']} km).", 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    if completed_date < log['scheduled_date']:
        conn.close()
        flash(f"Completed date cannot be earlier than scheduled date ({log['scheduled_date']}).", 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE maintenance_logs 
        SET status = 'Completed', completed_date = ?, end_date = ?, actual_cost = ?, cost = ?,
            work_performed = ?, parts_replaced = ?, remarks = ?, current_odometer = ?
        WHERE id = ?
    ''', (
        completed_date, completed_date, actual_cost, actual_cost,
        work_performed, parts_replaced, remarks, new_odometer, id
    ))
    
    cursor.execute('''
        UPDATE vehicles 
        SET status = 'Available', odometer = ? 
        WHERE id = ?
    ''', (new_odometer, log['vehicle_id']))
    
    # Look up assigned driver
    driver_row = conn.execute("SELECT id FROM drivers WHERE assigned_vehicle_id = ? AND status != 'Inactive'", (log['vehicle_id'],)).fetchone()
    m_driver_id = driver_row['id'] if driver_row else None
    
    # Calculate base amount and GST assuming 18% GST (standard commercial service tax in India)
    m_base = round(actual_cost / 1.18, 2)
    m_gst = round(actual_cost - m_base, 2)
    
    cursor.execute('''
        INSERT INTO expenses (vehicle_id, type, amount, date, description, driver_id, vendor, gst_percent, gst_amount, total_amount, payment_method, status, remarks)
        VALUES (?, 'Maintenance', ?, ?, ?, ?, ?, 18.0, ?, ?, 'Bank Transfer', 'Paid', ?)
    ''', (log['vehicle_id'], m_base, completed_date, f"Completed maintenance MNT-{id}: {log['maintenance_type']}", m_driver_id, log['service_center'] or "Bosch Car Service", m_gst, actual_cost, remarks or "Completed scheduled maintenance"))
    
    conn.commit()
    conn.close()
    
    flash(f"Maintenance job MNT-{id} completed successfully. Vehicle odometer updated.", 'success')
    return redirect(url_for('maintenance_details', id=id))

@app.route('/maintenance/cancel/<int:id>', methods=['POST'])
def maintenance_cancel(id):
    remarks = request.form.get('remarks', '').strip()
    if not remarks:
        flash('A cancellation reason is required.', 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    conn = get_db_connection()
    log = conn.execute("SELECT * FROM maintenance_logs WHERE id = ?", (id,)).fetchone()
    if not log:
        conn.close()
        flash('Maintenance record not found.', 'error')
        return redirect(url_for('maintenance_list'))
        
    if log['status'] not in ['Scheduled', 'In Progress', 'Overdue']:
        conn.close()
        flash('Only active jobs can be cancelled.', 'error')
        return redirect(url_for('maintenance_details', id=id))
        
    cursor = conn.cursor()
    cursor.execute("UPDATE maintenance_logs SET status = 'Cancelled', remarks = ? WHERE id = ?", (remarks, id))
    
    if log['status'] == 'In Progress':
        cursor.execute("UPDATE vehicles SET status = 'Available' WHERE id = ?", (log['vehicle_id'],))
        
    conn.commit()
    conn.close()
    
    flash(f"Maintenance job MNT-{id} has been Cancelled.", 'info')
    return redirect(url_for('maintenance_details', id=id))

def get_previous_fuel_log_odometer(conn, vehicle_id, current_date, current_id=None):
    if current_id:
        row = conn.execute("""
            SELECT odometer FROM fuel_logs
            WHERE vehicle_id = ? AND (date < ? OR (date = ? AND id < ?))
            ORDER BY date DESC, id DESC
            LIMIT 1
        """, (vehicle_id, current_date, current_date, current_id)).fetchone()
    else:
        row = conn.execute("""
            SELECT odometer FROM fuel_logs
            WHERE vehicle_id = ? AND date < ?
            ORDER BY date DESC, id DESC
            LIMIT 1
        """, (vehicle_id, current_date)).fetchone()
    return row['odometer'] if row else None

@app.route('/fuel')
def fuel_list():
    conn = get_db_connection()
    
    # 1. Fetch search and filter params
    q_search = request.args.get('q', '').strip()
    f_vehicle = request.args.get('vehicle', '').strip()
    f_driver = request.args.get('driver', '').strip()
    f_fuel_type = request.args.get('fuel_type', '').strip()
    f_payment_method = request.args.get('payment_method', '').strip()
    f_date_from = request.args.get('date_from', '').strip()
    f_date_to = request.args.get('date_to', '').strip()
    
    sort_by = request.args.get('sort_by', 'date').strip()
    sort_order = request.args.get('sort_order', 'DESC').strip()
    
    # 2. Build Query
    query = """
        SELECT f.*, v.registration_number AS vehicle_reg, v.name AS vehicle_name, v.type AS vehicle_type, v.status AS vehicle_status, d.name AS driver_name
        FROM fuel_logs f
        JOIN vehicles v ON f.vehicle_id = v.id
        LEFT JOIN drivers d ON f.driver_id = d.id
        WHERE 1=1
    """
    params = []
    
    if q_search:
        query += """ AND (
            f.id LIKE ? 
            OR v.registration_number LIKE ? 
            OR v.name LIKE ? 
            OR d.name LIKE ? 
            OR f.fuel_station LIKE ?
        )"""
        search_param = f"%{q_search}%"
        query_id = q_search.replace('FL-', '').replace('fl-', '')
        query_id_param = f"%{query_id}%" if query_id else search_param
        params.extend([query_id_param, search_param, search_param, search_param, search_param])
        
    if f_vehicle:
        query += " AND f.vehicle_id = ?"
        params.append(f_vehicle)
        
    if f_driver:
        query += " AND f.driver_id = ?"
        params.append(f_driver)
        
    if f_fuel_type:
        query += " AND f.fuel_type = ?"
        params.append(f_fuel_type)
        
    if f_payment_method:
        query += " AND f.payment_method = ?"
        params.append(f_payment_method)
        
    if f_date_from:
        query += " AND f.date >= ?"
        params.append(f_date_from)
        
    if f_date_to:
        query += " AND f.date <= ?"
        params.append(f_date_to + " 23:59")
        
    sort_map = {
        'date': 'f.date',
        'cost': 'f.cost',
        'quantity': 'f.liters',
        'vehicle': 'v.registration_number',
        'driver': 'd.name'
    }
    sort_column = sort_map.get(sort_by, 'f.date')
    if sort_order not in ['ASC', 'DESC']:
        sort_order = 'DESC'
        
    query += f" ORDER BY {sort_column} {sort_order}"
    
    raw_logs = conn.execute(query, params).fetchall()
    
    # Process Logs to compute mileage dynamically
    fuel_logs = []
    for log in raw_logs:
        log_dict = dict(log)
        prev_odo = get_previous_fuel_log_odometer(conn, log['vehicle_id'], log['date'], log['id'])
        distance = None
        mileage = None
        if prev_odo is not None:
            distance = log['odometer'] - prev_odo
            if distance > 0 and log['liters'] > 0:
                mileage = distance / log['liters']
        log_dict['distance'] = distance
        log_dict['mileage'] = mileage
        fuel_logs.append(log_dict)
        
    # 3. Calculate Global KPIs (unfiltered)
    total_records = conn.execute("SELECT COUNT(*) FROM fuel_logs").fetchone()[0] or 0
    total_cost = conn.execute("SELECT SUM(cost) FROM fuel_logs").fetchone()[0] or 0.0
    
    current_month_prefix = "2026-07"
    monthly_spent = conn.execute("SELECT SUM(cost) FROM fuel_logs WHERE date LIKE ?", (f"{current_month_prefix}%",)).fetchone()[0] or 0.0
    
    vehicles_count = conn.execute("SELECT COUNT(DISTINCT vehicle_id) FROM fuel_logs").fetchone()[0] or 1
    avg_cost_per_vehicle = total_cost / vehicles_count if vehicles_count > 0 else 0.0
    
    # Average Mileage of fleet
    fleet_mileages = []
    all_logs_raw = conn.execute("SELECT * FROM fuel_logs ORDER BY date ASC, id ASC").fetchall()
    odo_tracker = {}
    for log in all_logs_raw:
        v_id = log['vehicle_id']
        current_odo = log['odometer']
        if v_id in odo_tracker:
            dist = current_odo - odo_tracker[v_id]
            if dist > 0 and log['liters'] > 0:
                fleet_mileages.append(dist / log['liters'])
        odo_tracker[v_id] = current_odo
    avg_mileage = sum(fleet_mileages) / len(fleet_mileages) if fleet_mileages else None
    
    # Highest Consuming Vehicle
    max_row = conn.execute("""
        SELECT v.registration_number, SUM(f.cost) as total_spent, SUM(f.liters) as total_liters
        FROM fuel_logs f
        JOIN vehicles v ON f.vehicle_id = v.id
        GROUP BY f.vehicle_id
        ORDER BY total_spent DESC
        LIMIT 1
    """).fetchone()
    highest_consuming_vehicle = f"{max_row['registration_number']} (₹{max_row['total_spent']:,.0f})" if max_row else "None"
    
    kpis = {
        'total_records': total_records,
        'total_cost': total_cost,
        'monthly_spent': monthly_spent,
        'avg_cost_per_vehicle': avg_cost_per_vehicle,
        'avg_mileage': avg_mileage,
        'highest_consuming_vehicle': highest_consuming_vehicle
    }
    
    # 4. Dropdown options for Add modal and Filters
    active_vehicles = conn.execute("""
        SELECT v.id, v.registration_number, v.name, v.odometer, d.id AS assigned_driver_id
        FROM vehicles v
        LEFT JOIN drivers d ON d.assigned_vehicle_id = v.id AND d.status != 'Inactive'
        WHERE v.status != 'Retired'
        ORDER BY v.registration_number
    """).fetchall()
    vehicles = conn.execute("SELECT id, registration_number, name FROM vehicles ORDER BY registration_number").fetchall()
    drivers = conn.execute("SELECT id, name, employee_id FROM drivers ORDER BY name").fetchall()
    
    # 5. Vehicle Fuel Consumption & Mileage Analytics Summaries (Requirement 12)
    reports_stats = []
    vehicles_all = conn.execute("SELECT id, registration_number, name, type FROM vehicles ORDER BY registration_number").fetchall()
    for veh in vehicles_all:
        veh_logs = conn.execute("SELECT * FROM fuel_logs WHERE vehicle_id = ? ORDER BY date ASC, id ASC", (veh['id'],)).fetchall()
        if not veh_logs:
            continue
            
        v_total_cost = sum(log['cost'] for log in veh_logs)
        v_total_liters = sum(log['liters'] for log in veh_logs)
        
        v_mileages = []
        for idx in range(1, len(veh_logs)):
            dist = veh_logs[idx]['odometer'] - veh_logs[idx-1]['odometer']
            if dist > 0 and veh_logs[idx]['liters'] > 0:
                v_mileages.append(dist / veh_logs[idx]['liters'])
                
        v_avg_mileage = sum(v_mileages) / len(v_mileages) if v_mileages else None
        
        v_avg_cost_per_km = None
        if len(veh_logs) > 1:
            total_dist = veh_logs[-1]['odometer'] - veh_logs[0]['odometer']
            if total_dist > 0:
                v_avg_cost_per_km = sum(veh_logs[idx]['cost'] for idx in range(1, len(veh_logs))) / total_dist
                
        station_row = conn.execute("""
            SELECT fuel_station, COUNT(*) as count 
            FROM fuel_logs 
            WHERE vehicle_id = ? 
            GROUP BY fuel_station 
            ORDER BY count DESC, fuel_station ASC 
            LIMIT 1
        """, (veh['id'],)).fetchone()
        preferred_station = station_row['fuel_station'] if station_row else None
        
        reports_stats.append({
            'registration_number': veh['registration_number'],
            'name': veh['name'],
            'type': veh['type'],
            'total_cost': v_total_cost,
            'total_liters': v_total_liters,
            'avg_mileage': v_avg_mileage,
            'avg_cost_per_km': v_avg_cost_per_km,
            'preferred_station': preferred_station
        })
        
    conn.close()
    
    return render_template(
        'fuel/list.html',
        fuel_logs=fuel_logs,
        kpis=kpis,
        active_vehicles=active_vehicles,
        vehicles=vehicles,
        drivers=drivers,
        reports_stats=reports_stats,
        q_search=q_search,
        f_vehicle=f_vehicle,
        f_driver=f_driver,
        f_fuel_type=f_fuel_type,
        f_payment_method=f_payment_method,
        f_date_from=f_date_from,
        f_date_to=f_date_to,
        sort_by=sort_by,
        sort_order=sort_order,
        active_page='fuel'
    )

@app.route('/fuel/<int:id>')
def fuel_details(id):
    conn = get_db_connection()
    log = conn.execute("""
        SELECT f.*, v.registration_number AS vehicle_reg, v.name AS vehicle_name, v.type AS vehicle_type, v.status AS vehicle_status,
               d.name AS driver_name, d.license_number AS driver_license, d.employee_id AS driver_employee_id, d.safety_score AS driver_safety
        FROM fuel_logs f
        JOIN vehicles v ON f.vehicle_id = v.id
        LEFT JOIN drivers d ON f.driver_id = d.id
        WHERE f.id = ?
    """, (id,)).fetchone()
    if not log:
        conn.close()
        flash("Fuel record not found.", "error")
        return redirect(url_for('fuel_list'))
    
    # Calculate mileage
    prev_odo = get_previous_fuel_log_odometer(conn, log['vehicle_id'], log['date'], log['id'])
    distance = None
    mileage = None
    if prev_odo is not None:
        distance = log['odometer'] - prev_odo
        if distance > 0 and log['liters'] > 0:
            mileage = distance / log['liters']
            
    # convert row to dict
    log_dict = dict(log)
    log_dict['distance'] = distance
    log_dict['mileage'] = mileage
    
    conn.close()
    return render_template('fuel/details.html', log=log_dict, active_page='fuel')

@app.route('/fuel/add', methods=['POST'])
def fuel_add():
    vehicle_id = request.form.get('vehicle_id')
    driver_id = request.form.get('driver_id')
    fuel_type = request.form.get('fuel_type')
    fuel_station = request.form.get('fuel_station', '').strip()
    liters = request.form.get('liters')
    price_per_liter = request.form.get('price_per_liter')
    odometer = request.form.get('odometer')
    date = request.form.get('date')
    payment_method = request.form.get('payment_method')
    remarks = request.form.get('remarks', '').strip()
    
    if date and 'T' in date:
        date = date.replace('T', ' ')
        
    if not vehicle_id or not driver_id or not fuel_type or not fuel_station or not liters or not price_per_liter or not odometer or not date or not payment_method:
        flash("All fields are required.", "error")
        return redirect(url_for('fuel_list'))
        
    try:
        liters = float(liters)
        price_per_liter = float(price_per_liter)
        odometer = float(odometer)
    except ValueError:
        flash("Invalid numeric format.", "error")
        return redirect(url_for('fuel_list'))
        
    if liters <= 0:
        flash("Fuel quantity must be greater than zero.", "error")
        return redirect(url_for('fuel_list'))
        
    if price_per_liter <= 0:
        flash("Price per litre must be greater than zero.", "error")
        return redirect(url_for('fuel_list'))
        
    conn = get_db_connection()
    vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    if not vehicle:
        conn.close()
        flash("Vehicle not found.", "error")
        return redirect(url_for('fuel_list'))
        
    # Active vehicle check
    if vehicle['status'] == 'Retired':
        conn.close()
        flash("Retired vehicles cannot receive fuel records.", "error")
        return redirect(url_for('fuel_list'))
        
    # Odometer rollback validation
    if odometer < vehicle['odometer']:
        conn.close()
        flash(f"Odometer reading cannot be less than the vehicle's current odometer ({vehicle['odometer']} km).", "error")
        return redirect(url_for('fuel_list'))
        
    # Driver assignment validation
    assigned_driver = conn.execute("SELECT * FROM drivers WHERE assigned_vehicle_id = ?", (vehicle_id,)).fetchone()
    if assigned_driver and int(driver_id) != assigned_driver['id']:
        conn.close()
        flash(f"Driver {assigned_driver['name']} is assigned to this vehicle. Only the assigned driver can log fuel.", "error")
        return redirect(url_for('fuel_list'))
        
    cost = round(liters * price_per_liter, 2)
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO fuel_logs (vehicle_id, driver_id, fuel_type, fuel_station, liters, price_per_liter, cost, odometer, date, payment_method, remarks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (vehicle_id, driver_id, fuel_type, fuel_station, liters, price_per_liter, cost, odometer, date, payment_method, remarks))
    
    fuel_id = cursor.lastrowid
    
    if odometer > vehicle['odometer']:
        conn.execute("UPDATE vehicles SET odometer = ? WHERE id = ?", (odometer, vehicle_id))
        
    conn.execute("""
        INSERT INTO expenses (vehicle_id, type, amount, date, description, driver_id, vendor, gst_percent, gst_amount, total_amount, payment_method, status, remarks)
        VALUES (?, 'Fuel', ?, ?, ?, ?, ?, 0.0, 0.0, ?, ?, 'Paid', ?)
    """, (vehicle_id, cost, date[:10], f"Refuel at {fuel_station}: {liters}L of {fuel_type} (FL-{fuel_id})", driver_id, fuel_station, cost, payment_method, remarks))
    
    conn.commit()
    conn.close()
    
    flash("Fuel record logged successfully!", "success")
    return redirect(url_for('fuel_list'))

@app.route('/fuel/edit/<int:id>', methods=['GET', 'POST'])
def fuel_edit(id):
    conn = get_db_connection()
    log = conn.execute("SELECT * FROM fuel_logs WHERE id = ?", (id,)).fetchone()
    if not log:
        conn.close()
        flash("Fuel record not found.", "error")
        return redirect(url_for('fuel_list'))
        
    if request.method == 'POST':
        vehicle_id = request.form.get('vehicle_id')
        driver_id = request.form.get('driver_id')
        fuel_type = request.form.get('fuel_type')
        fuel_station = request.form.get('fuel_station', '').strip()
        liters = request.form.get('liters')
        price_per_liter = request.form.get('price_per_liter')
        odometer = request.form.get('odometer')
        date = request.form.get('date')
        payment_method = request.form.get('payment_method')
        remarks = request.form.get('remarks', '').strip()
        
        if date and 'T' in date:
            date = date.replace('T', ' ')
            
        if not vehicle_id or not driver_id or not fuel_type or not fuel_station or not liters or not price_per_liter or not odometer or not date or not payment_method:
            conn.close()
            flash("All fields are required.", "error")
            return redirect(url_for('fuel_edit', id=id))
            
        try:
            liters = float(liters)
            price_per_liter = float(price_per_liter)
            odometer = float(odometer)
        except ValueError:
            conn.close()
            flash("Invalid numeric format.", "error")
            return redirect(url_for('fuel_edit', id=id))
            
        if liters <= 0 or price_per_liter <= 0:
            conn.close()
            flash("Liters and price must be greater than zero.", "error")
            return redirect(url_for('fuel_edit', id=id))
            
        vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
        if not vehicle:
            conn.close()
            flash("Vehicle not found.", "error")
            return redirect(url_for('fuel_edit', id=id))
            
        if vehicle['status'] == 'Retired':
            conn.close()
            flash("Retired vehicles cannot receive fuel records.", "error")
            return redirect(url_for('fuel_edit', id=id))
            
        prev_odo = get_previous_fuel_log_odometer(conn, vehicle_id, date, id)
        if prev_odo is not None and odometer < prev_odo:
            conn.close()
            flash(f"Odometer cannot be less than the previous fuel entry's odometer ({prev_odo} km).", "error")
            return redirect(url_for('fuel_edit', id=id))
            
        assigned_driver = conn.execute("SELECT * FROM drivers WHERE assigned_vehicle_id = ?", (vehicle_id,)).fetchone()
        if assigned_driver and int(driver_id) != assigned_driver['id']:
            conn.close()
            flash(f"Driver {assigned_driver['name']} is assigned to this vehicle. Only the assigned driver can log fuel.", "error")
            return redirect(url_for('fuel_edit', id=id))
            
        cost = round(liters * price_per_liter, 2)
        
        conn.execute("""
            UPDATE fuel_logs
            SET vehicle_id = ?, driver_id = ?, fuel_type = ?, fuel_station = ?, liters = ?, price_per_liter = ?, cost = ?, odometer = ?, date = ?, payment_method = ?, remarks = ?
            WHERE id = ?
        """, (vehicle_id, driver_id, fuel_type, fuel_station, liters, price_per_liter, cost, odometer, date, payment_method, remarks, id))
        
        if odometer > vehicle['odometer']:
            conn.execute("UPDATE vehicles SET odometer = ? WHERE id = ?", (odometer, vehicle_id))
            
        conn.execute("""
            UPDATE expenses
            SET vehicle_id = ?, amount = ?, date = ?, description = ?, driver_id = ?, vendor = ?, total_amount = ?, payment_method = ?, remarks = ?
            WHERE description LIKE ?
        """, (vehicle_id, cost, date[:10], f"Refuel at {fuel_station}: {liters}L of {fuel_type} (FL-{id})", driver_id, fuel_station, cost, payment_method, remarks, f"%(FL-{id})%"))
        
        conn.commit()
        conn.close()
        flash("Fuel record updated successfully!", "success")
        return redirect(url_for('fuel_details', id=id))
        
    vehicles = conn.execute("SELECT id, registration_number, name, odometer FROM vehicles WHERE status != 'Retired' ORDER BY registration_number").fetchall()
    drivers = conn.execute("SELECT id, name, employee_id FROM drivers ORDER BY name").fetchall()
    conn.close()
    return render_template('fuel/edit.html', log=log, vehicles=vehicles, drivers=drivers, active_page='fuel')

@app.route('/fuel/delete/<int:id>', methods=['POST'])
def fuel_delete(id):
    conn = get_db_connection()
    log = conn.execute("SELECT * FROM fuel_logs WHERE id = ?", (id,)).fetchone()
    if not log:
        conn.close()
        flash("Fuel record not found.", "error")
        return redirect(url_for('fuel_list'))
        
    conn.execute("DELETE FROM fuel_logs WHERE id = ?", (id,))
    conn.execute("DELETE FROM expenses WHERE description LIKE ?", (f"%(FL-{id})%",))
    conn.commit()
    conn.close()
    
    flash(f"Fuel record FL-{id} deleted successfully.", "success")
    return redirect(url_for('fuel_list'))

@app.route('/expenses')
def expenses_list():
    from datetime import datetime
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    # Base query for expenses
    query = """
        SELECT e.*, v.registration_number, v.name as vehicle_name, d.name as driver_name, t.source, t.destination
        FROM expenses e
        LEFT JOIN vehicles v ON e.vehicle_id = v.id
        LEFT JOIN drivers d ON e.driver_id = d.id
        LEFT JOIN trips t ON e.trip_id = t.id
        WHERE 1=1
    """
    params = []
    
    # Fetch filter parameters
    q_search = request.args.get('q', '').strip()
    f_category = request.args.get('category', '').strip()
    f_vehicle = request.args.get('vehicle', '').strip()
    f_driver = request.args.get('driver', '').strip()
    f_status = request.args.get('status', '').strip()
    f_payment = request.args.get('payment_method', '').strip()
    f_start_date = request.args.get('start_date', '').strip()
    f_end_date = request.args.get('end_date', '').strip()
    
    if q_search:
        query += " AND (CAST(e.id AS TEXT) LIKE ? OR v.registration_number LIKE ? OR e.vendor LIKE ? OR d.name LIKE ? OR e.type LIKE ?)"
        like_q = f"%{q_search}%"
        params.extend([like_q, like_q, like_q, like_q, like_q])
        
    if f_category:
        query += " AND e.type = ?"
        params.append(f_category)
        
    if f_vehicle:
        query += " AND e.vehicle_id = ?"
        params.append(int(f_vehicle))
        
    if f_driver:
        query += " AND e.driver_id = ?"
        params.append(int(f_driver))
        
    if f_status:
        query += " AND e.status = ?"
        params.append(f_status)
        
    if f_payment:
        query += " AND e.payment_method = ?"
        params.append(f_payment)
        
    if f_start_date:
        query += " AND substr(e.date, 1, 10) >= ?"
        params.append(f_start_date)
        
    if f_end_date:
        query += " AND substr(e.date, 1, 10) <= ?"
        params.append(f_end_date)
        
    # Sorting
    sort_by = request.args.get('sort', 'date').strip()
    sort_order = request.args.get('order', 'desc').strip()
    if sort_order not in ['asc', 'desc']:
        sort_order = 'desc'
        
    allowed_sorts = {
        'date': 'e.date',
        'amount': 'e.total_amount',
        'category': 'e.type',
        'vehicle': 'v.registration_number',
        'vendor': 'e.vendor'
    }
    sort_column = allowed_sorts.get(sort_by, 'e.date')
    
    query += f" ORDER BY {sort_column} {sort_order.upper()}, e.id DESC"
    
    expenses_list = conn.execute(query, params).fetchall()
    
    # Calculate Dashboard KPIs (Cancelled expenses ignored)
    today_str = datetime.now().strftime('%Y-%m-%d')
    current_month_str = datetime.now().strftime('%Y-%m')
    
    kpis = {}
    
    # Total Expenses (non-cancelled)
    total_spent_row = conn.execute("SELECT SUM(total_amount) FROM expenses WHERE status != 'Cancelled'").fetchone()
    kpis['total_spent'] = total_spent_row[0] if total_spent_row[0] is not None else 0.0
    
    # Monthly Spend (non-cancelled, this month)
    monthly_spent_row = conn.execute("SELECT SUM(total_amount) FROM expenses WHERE status != 'Cancelled' AND substr(date, 1, 7) = ?", (current_month_str,)).fetchone()
    kpis['monthly_spent'] = monthly_spent_row[0] if monthly_spent_row[0] is not None else 0.0
    
    # Today's Spend (non-cancelled)
    today_spent_row = conn.execute("SELECT SUM(total_amount) FROM expenses WHERE status != 'Cancelled' AND substr(date, 1, 10) = ?", (today_str,)).fetchone()
    kpis['today_spent'] = today_spent_row[0] if today_spent_row[0] is not None else 0.0
    
    # Pending Payments
    pending_spent_row = conn.execute("SELECT SUM(total_amount) FROM expenses WHERE status = 'Pending'").fetchone()
    kpis['pending_spent'] = pending_spent_row[0] if pending_spent_row[0] is not None else 0.0
    
    # Paid Expenses
    paid_spent_row = conn.execute("SELECT SUM(total_amount) FROM expenses WHERE status = 'Paid'").fetchone()
    kpis['paid_spent'] = paid_spent_row[0] if paid_spent_row[0] is not None else 0.0
    
    # Highest Expense Category
    highest_cat_row = conn.execute("""
        SELECT type, SUM(total_amount) as total
        FROM expenses
        WHERE status != 'Cancelled'
        GROUP BY type
        ORDER BY total DESC
        LIMIT 1
    """).fetchone()
    kpis['highest_category'] = f"{highest_cat_row['type']} (₹{highest_cat_row['total']:,.2f})" if highest_cat_row else "N/A"
    
    # Average Monthly Spend
    avg_spent_row = conn.execute("""
        SELECT COUNT(DISTINCT substr(date, 1, 7)) as months_count, SUM(total_amount) as total
        FROM expenses
        WHERE status != 'Cancelled'
    """).fetchone()
    months_count = avg_spent_row['months_count'] if avg_spent_row and avg_spent_row['months_count'] else 1
    total_amount_sum = avg_spent_row['total'] if avg_spent_row and avg_spent_row['total'] else 0.0
    kpis['avg_monthly_spend'] = total_amount_sum / months_count
    
    # Reports & Chart Analytics
    monthly_report = conn.execute("""
        SELECT substr(date, 1, 7) as month, SUM(total_amount) as total, COUNT(*) as count
        FROM expenses
        WHERE status != 'Cancelled'
        GROUP BY month
        ORDER BY month DESC
    """).fetchall()
    
    category_report = conn.execute("""
        SELECT type as category, SUM(total_amount) as total, COUNT(*) as count
        FROM expenses
        WHERE status != 'Cancelled'
        GROUP BY category
        ORDER BY total DESC
    """).fetchall()
    
    vehicle_report = conn.execute("""
        SELECT v.registration_number, v.name, SUM(e.total_amount) as total, COUNT(*) as count
        FROM expenses e
        JOIN vehicles v ON e.vehicle_id = v.id
        WHERE e.status != 'Cancelled'
        GROUP BY v.id, v.registration_number, v.name
        ORDER BY total DESC
    """).fetchall()
    
    fuel_vs_maint = conn.execute("""
        SELECT 
            SUM(CASE WHEN type = 'Fuel' THEN total_amount ELSE 0 END) as fuel_total,
            SUM(CASE WHEN type = 'Maintenance' THEN total_amount ELSE 0 END) as maint_total
        FROM expenses
        WHERE status != 'Cancelled'
    """).fetchone()
    
    top_5_expenses = conn.execute("""
        SELECT e.*, v.registration_number, d.name as driver_name
        FROM expenses e
        JOIN vehicles v ON e.vehicle_id = v.id
        LEFT JOIN drivers d ON e.driver_id = d.id
        WHERE e.status != 'Cancelled'
        ORDER BY e.total_amount DESC
        LIMIT 5
    """).fetchall()
    
    # Dropdowns list options
    vehicles = conn.execute("SELECT id, registration_number, name FROM vehicles WHERE status != 'Retired' ORDER BY registration_number").fetchall()
    drivers = conn.execute("SELECT id, name, employee_id FROM drivers WHERE status != 'Inactive' ORDER BY name").fetchall()
    trips = conn.execute("SELECT id, source, destination, dispatch_date FROM trips ORDER BY id DESC").fetchall()
    
    categories = [
        'Fuel', 'Maintenance', 'Driver Salary', 'Insurance', 'Vehicle Registration',
        'Toll Charges', 'Parking Fees', 'Traffic Fines', 'Tyre Replacement', 'Office Expenses', 'Miscellaneous'
    ]
    
    conn.close()
    
    return render_template(
        'expenses/list.html',
        active_page='expenses',
        expenses=expenses_list,
        kpis=kpis,
        vehicles=vehicles,
        drivers=drivers,
        trips=trips,
        categories=categories,
        monthly_report=monthly_report,
        category_report=category_report,
        vehicle_report=vehicle_report,
        fuel_vs_maint=fuel_vs_maint,
        top_5_expenses=top_5_expenses,
        q_search=q_search,
        f_category=f_category,
        f_vehicle=f_vehicle,
        f_driver=f_driver,
        f_status=f_status,
        f_payment=f_payment,
        f_start_date=f_start_date,
        f_end_date=f_end_date,
        sort_by=sort_by,
        sort_order=sort_order
    )

@app.route('/expenses/add', methods=['POST'])
def expenses_add():
    from datetime import datetime
    vehicle_id = request.form.get('vehicle_id')
    driver_id = request.form.get('driver_id') or None
    trip_id = request.form.get('trip_id') or None
    category = request.form.get('category')
    vendor = request.form.get('vendor', '').strip()
    date = request.form.get('date')
    amount = request.form.get('amount')
    gst_percent = request.form.get('gst_percent', '0')
    payment_method = request.form.get('payment_method')
    status = request.form.get('status')
    remarks = request.form.get('remarks', '').strip()
    attachment = request.form.get('attachment', '').strip() or None
    
    if not vehicle_id or not category or not date or not amount or not payment_method or not status:
        flash("Vehicle, Category, Date, Amount, Payment Method, and Status are required fields.", "error")
        return redirect(url_for('expenses_list'))
        
    try:
        amount = float(amount)
        gst_percent = float(gst_percent)
    except ValueError:
        flash("Invalid numeric format for amount or GST.", "error")
        return redirect(url_for('expenses_list'))
        
    if amount <= 0:
        flash("Amount must be greater than zero.", "error")
        return redirect(url_for('expenses_list'))
        
    if gst_percent < 0:
        flash("GST percentage cannot be negative.", "error")
        return redirect(url_for('expenses_list'))
        
    today_str = datetime.now().strftime('%Y-%m-%d')
    if date > today_str:
        flash("Expense Date cannot be in the future.", "error")
        return redirect(url_for('expenses_list'))
        
    # GST auto calculations
    gst_amount = round(amount * (gst_percent / 100.0), 2)
    total_amount = round(amount + gst_amount, 2)
    
    conn = get_db_connection()
    vehicle = conn.execute("SELECT id FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    if not vehicle:
        conn.close()
        flash("Vehicle not found.", "error")
        return redirect(url_for('expenses_list'))
        
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO expenses (vehicle_id, type, amount, date, description, driver_id, trip_id, vendor, gst_percent, gst_amount, total_amount, payment_method, status, remarks, attachment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (vehicle_id, category, amount, date, f"Manual: {category} expense", driver_id, trip_id, vendor, gst_percent, gst_amount, total_amount, payment_method, status, remarks, attachment))
    
    conn.commit()
    conn.close()
    
    flash("Expense added successfully!", "success")
    return redirect(url_for('expenses_list'))

@app.route('/expenses/details/<int:id>')
def expenses_details(id):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    expense = conn.execute("""
        SELECT e.*, v.registration_number, v.name as vehicle_name, d.name as driver_name, t.source, t.destination, t.dispatch_date
        FROM expenses e
        LEFT JOIN vehicles v ON e.vehicle_id = v.id
        LEFT JOIN drivers d ON e.driver_id = d.id
        LEFT JOIN trips t ON e.trip_id = t.id
        WHERE e.id = ?
    """, (id,)).fetchone()
    if not expense:
        conn.close()
        flash("Expense record not found.", "error")
        return redirect(url_for('expenses_list'))
    conn.close()
    return render_template('expenses/details.html', expense=expense, active_page='expenses')

@app.route('/expenses/edit/<int:id>', methods=['GET', 'POST'])
def expenses_edit(id):
    from datetime import datetime
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    expense = conn.execute("SELECT * FROM expenses WHERE id = ?", (id,)).fetchone()
    if not expense:
        conn.close()
        flash("Expense not found.", "error")
        return redirect(url_for('expenses_list'))
        
    if request.method == 'POST':
        vehicle_id = request.form.get('vehicle_id')
        driver_id = request.form.get('driver_id') or None
        trip_id = request.form.get('trip_id') or None
        category = request.form.get('category')
        vendor = request.form.get('vendor', '').strip()
        date = request.form.get('date')
        amount = request.form.get('amount')
        gst_percent = request.form.get('gst_percent', '0')
        payment_method = request.form.get('payment_method')
        status = request.form.get('status')
        remarks = request.form.get('remarks', '').strip()
        attachment = request.form.get('attachment', '').strip() or None
        
        if not vehicle_id or not category or not date or not amount or not payment_method or not status:
            conn.close()
            flash("Vehicle, Category, Date, Amount, Payment Method, and Status are required fields.", "error")
            return redirect(url_for('expenses_edit', id=id))
            
        try:
            amount = float(amount)
            gst_percent = float(gst_percent)
        except ValueError:
            conn.close()
            flash("Invalid numeric format for amount or GST.", "error")
            return redirect(url_for('expenses_edit', id=id))
            
        if amount <= 0:
            conn.close()
            flash("Amount must be greater than zero.", "error")
            return redirect(url_for('expenses_edit', id=id))
            
        if gst_percent < 0:
            conn.close()
            flash("GST percentage cannot be negative.", "error")
            return redirect(url_for('expenses_edit', id=id))
            
        today_str = datetime.now().strftime('%Y-%m-%d')
        if date > today_str:
            conn.close()
            flash("Expense Date cannot be in the future.", "error")
            return redirect(url_for('expenses_edit', id=id))
            
        # GST calculations
        gst_amount = round(amount * (gst_percent / 100.0), 2)
        total_amount = round(amount + gst_amount, 2)
        
        # Verify vehicle
        vehicle = conn.execute("SELECT id FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
        if not vehicle:
            conn.close()
            flash("Vehicle not found.", "error")
            return redirect(url_for('expenses_edit', id=id))
            
        conn.execute("""
            UPDATE expenses
            SET vehicle_id = ?, type = ?, amount = ?, date = ?, description = ?, driver_id = ?, trip_id = ?, vendor = ?, gst_percent = ?, gst_amount = ?, total_amount = ?, payment_method = ?, status = ?, remarks = ?, attachment = ?
            WHERE id = ?
        """, (vehicle_id, category, amount, date, f"Manual: {category} expense", driver_id, trip_id, vendor, gst_percent, gst_amount, total_amount, payment_method, status, remarks, attachment, id))
        
        conn.commit()
        conn.close()
        flash("Expense updated successfully!", "success")
        return redirect(url_for('expenses_list'))
        
    vehicles = conn.execute("SELECT id, registration_number, name FROM vehicles WHERE status != 'Retired' ORDER BY registration_number").fetchall()
    drivers = conn.execute("SELECT id, name, employee_id FROM drivers WHERE status != 'Inactive' ORDER BY name").fetchall()
    trips = conn.execute("SELECT id, source, destination, dispatch_date FROM trips ORDER BY id DESC").fetchall()
    
    categories = [
        'Fuel', 'Maintenance', 'Driver Salary', 'Insurance', 'Vehicle Registration',
        'Toll Charges', 'Parking Fees', 'Traffic Fines', 'Tyre Replacement', 'Office Expenses', 'Miscellaneous'
    ]
    
    conn.close()
    return render_template('expenses/edit.html', expense=expense, vehicles=vehicles, drivers=drivers, trips=trips, categories=categories, active_page='expenses')

@app.route('/expenses/delete/<int:id>', methods=['POST'])
def expenses_delete(id):
    conn = get_db_connection()
    expense = conn.execute("SELECT * FROM expenses WHERE id = ?", (id,)).fetchone()
    if not expense:
        conn.close()
        flash("Expense record not found.", "error")
        return redirect(url_for('expenses_list'))
        
    conn.execute("DELETE FROM expenses WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("Expense record deleted successfully.", "success")
    return redirect(url_for('expenses_list'))

@app.route('/reports')
def reports():
    conn = get_db_connection()
    
    # 1. Maintenance stats (Backwards compatibility)
    query = """
        SELECT 
            v.id,
            v.registration_number,
            v.name,
            v.type,
            v.status,
            v.odometer,
            COUNT(CASE WHEN m.status = 'Completed' THEN 1 END) AS total_services,
            MAX(CASE WHEN m.status = 'Completed' THEN m.completed_date END) AS last_service_date,
            SUM(CASE WHEN m.status = 'Completed' THEN m.actual_cost ELSE 0 END) AS total_cost,
            AVG(CASE WHEN m.status = 'Completed' THEN m.actual_cost END) AS avg_cost
        FROM vehicles v
        LEFT JOIN maintenance_logs m ON v.id = m.vehicle_id
        GROUP BY v.id, v.registration_number, v.name, v.type, v.status, v.odometer
        ORDER BY total_cost DESC
    """
    vehicle_stats = conn.execute(query).fetchall()
    
    type_query = """
        SELECT maintenance_type, COUNT(*) as count, SUM(actual_cost) as total_cost
        FROM maintenance_logs
        WHERE status = 'Completed'
        GROUP BY maintenance_type
        ORDER BY count DESC
    """
    type_stats = conn.execute(type_query).fetchall()
    
    trend_query = """
        SELECT completed_date, SUM(actual_cost) as daily_cost
        FROM maintenance_logs
        WHERE status = 'Completed' AND completed_date IS NOT NULL
        GROUP BY completed_date
        ORDER BY completed_date ASC
        LIMIT 30
    """
    trend_stats = conn.execute(trend_query).fetchall()
    
    # 2. Rich reports datasets
    vehicles = conn.execute("SELECT * FROM vehicles ORDER BY registration_number").fetchall()
    drivers = conn.execute("""
        SELECT d.*, v.registration_number as vehicle_reg,
               COUNT(t.id) as trips_count,
               SUM(CASE WHEN t.status = 'Completed' THEN t.planned_distance ELSE 0 END) as distance_driven
        FROM drivers d
        LEFT JOIN vehicles v ON d.assigned_vehicle_id = v.id
        LEFT JOIN trips t ON d.id = t.driver_id
        GROUP BY d.id
        ORDER BY d.name
    """).fetchall()
    
    trips = conn.execute("""
        SELECT t.*, v.registration_number as vehicle_reg, d.name as driver_name
        FROM trips t
        JOIN vehicles v ON t.vehicle_id = v.id
        JOIN drivers d ON t.driver_id = d.id
        ORDER BY t.created_at DESC
    """).fetchall()
    
    fuel_logs = conn.execute("""
        SELECT f.*, v.registration_number as vehicle_reg, d.name as driver_name
        FROM fuel_logs f
        JOIN vehicles v ON f.vehicle_id = v.id
        LEFT JOIN drivers d ON f.driver_id = d.id
        ORDER BY f.date DESC
    """).fetchall()
    
    maintenance_logs = conn.execute("""
        SELECT m.*, v.registration_number as vehicle_reg
        FROM maintenance_logs m
        JOIN vehicles v ON m.vehicle_id = v.id
        ORDER BY m.start_date DESC
    """).fetchall()
    
    expenses = conn.execute("""
        SELECT e.*, v.registration_number as vehicle_reg, d.name as driver_name
        FROM expenses e
        JOIN vehicles v ON e.vehicle_id = v.id
        LEFT JOIN drivers d ON e.driver_id = d.id
        ORDER BY e.date DESC
    """).fetchall()
    
    conn.close()
    
    return render_template(
        'reports.html',
        active_page='reports',
        vehicle_stats=vehicle_stats,
        type_stats=type_stats,
        trend_stats=trend_stats,
        vehicles=vehicles,
        drivers=drivers,
        trips=trips,
        fuel_logs=fuel_logs,
        maintenance_logs=maintenance_logs,
        expenses=expenses
    )

@app.route('/reports/export')
def reports_export():
    report_type = request.args.get('type', 'fleet')
    conn = get_db_connection()
    
    import csv
    import io
    from flask import Response
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    if report_type == 'fleet':
        writer.writerow(['Metric', 'Value'])
        total_vehicles = conn.execute('SELECT COUNT(*) FROM vehicles').fetchone()[0] or 0
        available_vehicles = conn.execute('SELECT COUNT(*) FROM vehicles WHERE status = "Available"').fetchone()[0] or 0
        on_trip_vehicles = conn.execute('SELECT COUNT(*) FROM vehicles WHERE status = "On Trip"').fetchone()[0] or 0
        total_drivers = conn.execute('SELECT COUNT(*) FROM drivers').fetchone()[0] or 0
        active_trips = conn.execute('SELECT COUNT(*) FROM trips WHERE status IN ("In Progress", "Dispatched")').fetchone()[0] or 0
        total_spent = conn.execute('SELECT SUM(total_amount) FROM expenses WHERE status = "Paid"').fetchone()[0] or 0.0
        
        writer.writerow(['Total Vehicles', total_vehicles])
        writer.writerow(['Available Vehicles', available_vehicles])
        writer.writerow(['Vehicles On Trip', on_trip_vehicles])
        writer.writerow(['Total Drivers', total_drivers])
        writer.writerow(['Active Trips', active_trips])
        writer.writerow(['Total Cumulative Expenses (INR)', total_spent])
        
    elif report_type == 'vehicle':
        writer.writerow(['ID', 'Registration Number', 'Name', 'Type', 'Capacity (kg)', 'Odometer (km)', 'Acquisition Cost', 'Status', 'Region'])
        vehicles = conn.execute('SELECT * FROM vehicles').fetchall()
        for v in vehicles:
            writer.writerow([v['id'], v['registration_number'], v['name'], v['type'], v['max_load_capacity'], v['odometer'], v['acquisition_cost'], v['status'], v['region']])
            
    elif report_type == 'driver':
        writer.writerow(['ID', 'Employee ID', 'Name', 'License Number', 'Category', 'Expiry Date', 'Contact', 'Safety Score', 'Status', 'Region'])
        drivers = conn.execute('SELECT * FROM drivers').fetchall()
        for d in drivers:
            writer.writerow([d['id'], d['employee_id'], d['name'], d['license_number'], d['license_category'], d['license_expiry_date'], d['contact_number'], d['safety_score'], d['status'], d['region']])
            
    elif report_type == 'trip':
        writer.writerow(['ID', 'Source', 'Destination', 'Vehicle ID', 'Driver ID', 'Cargo Weight (kg)', 'Distance (km)', 'Status', 'Revenue', 'Fuel Consumed (L)', 'Dispatch Date', 'Return Date'])
        trips = conn.execute('SELECT * FROM trips').fetchall()
        for t in trips:
            writer.writerow([t['id'], t['source'], t['destination'], t['vehicle_id'], t['driver_id'], t['cargo_weight'], t['planned_distance'], t['status'], t['revenue'], t['fuel_consumed'], t['dispatch_date'], t['actual_return']])
            
    elif report_type == 'fuel':
        writer.writerow(['ID', 'Vehicle ID', 'Driver ID', 'Fuel Type', 'Fuel Station', 'Liters', 'Price/L', 'Total Cost', 'Odometer', 'Date', 'Payment Method'])
        fuel = conn.execute('SELECT * FROM fuel_logs').fetchall()
        for f in fuel:
            writer.writerow([f['id'], f['vehicle_id'], f['driver_id'], f['fuel_type'], f['fuel_station'], f['liters'], f['price_per_liter'], f['cost'], f['odometer'], f['date'], f['payment_method']])
            
    elif report_type == 'maintenance':
        writer.writerow(['ID', 'Vehicle ID', 'Type', 'Service Center', 'Technician', 'Status', 'Scheduled Date', 'Completed Date', 'Est Cost', 'Actual Cost', 'Odometer', 'Description'])
        maint = conn.execute('SELECT * FROM maintenance_logs').fetchall()
        for m in maint:
            writer.writerow([m['id'], m['vehicle_id'], m['maintenance_type'], m['service_center'], m['technician_name'], m['status'], m['scheduled_date'], m['completed_date'], m['estimated_cost'], m['actual_cost'], m['current_odometer'], m['description']])
            
    elif report_type == 'expense':
        writer.writerow(['ID', 'Vehicle ID', 'Type', 'Amount', 'Date', 'Description', 'Vendor', 'GST %', 'GST Amount', 'Total Amount', 'Payment Method', 'Status'])
        exp = conn.execute('SELECT * FROM expenses').fetchall()
        for e in exp:
            writer.writerow([e['id'], e['vehicle_id'], e['type'], e['amount'], e['date'], e['description'], e['vendor'], e['gst_percent'], e['gst_amount'], e['total_amount'], e['payment_method'], e['status']])
            
    conn.close()
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={report_type}_report.csv"}
    )

@app.route('/reports/print')
def reports_print():
    report_type = request.args.get('type', 'all')
    conn = get_db_connection()
    
    vehicles = conn.execute('SELECT * FROM vehicles ORDER BY registration_number').fetchall()
    drivers = conn.execute('SELECT * FROM drivers ORDER BY name').fetchall()
    trips = conn.execute('SELECT t.*, v.registration_number as vehicle_reg, d.name as driver_name FROM trips t JOIN vehicles v ON t.vehicle_id = v.id JOIN drivers d ON t.driver_id = d.id ORDER BY t.created_at DESC').fetchall()
    fuel = conn.execute('SELECT f.*, v.registration_number as vehicle_reg FROM fuel_logs f JOIN vehicles v ON f.vehicle_id = v.id ORDER BY f.date DESC').fetchall()
    maintenance = conn.execute('SELECT m.*, v.registration_number as vehicle_reg FROM maintenance_logs m JOIN vehicles v ON m.vehicle_id = v.id ORDER BY m.start_date DESC').fetchall()
    expenses = conn.execute('SELECT e.*, v.registration_number as vehicle_reg FROM expenses e JOIN vehicles v ON e.vehicle_id = v.id ORDER BY e.date DESC').fetchall()
    
    conn.close()
    return render_template(
        'print_report.html',
        report_type=report_type,
        vehicles=vehicles,
        drivers=drivers,
        trips=trips,
        fuel=fuel,
        maintenance=maintenance,
        expenses=expenses
    )

if __name__ == '__main__':
    # Flask app listens on port 3000 to match container routing requirements
    app.run(host='0.0.0.0', port=3000, debug=True)
