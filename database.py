import sqlite3
import os
import hashlib

DB_FILE = 'transitops.db'

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')

    # 2. Vehicles Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            registration_number TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            max_load_capacity REAL NOT NULL,
            odometer REAL NOT NULL,
            acquisition_cost REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'Available',
            region TEXT NOT NULL
        )
    ''')

    # 3. Drivers Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            license_number TEXT UNIQUE NOT NULL,
            license_category TEXT NOT NULL,
            license_expiry_date TEXT NOT NULL,
            contact_number TEXT NOT NULL,
            safety_score REAL NOT NULL DEFAULT 100.0,
            status TEXT NOT NULL DEFAULT 'Available',
            employee_id TEXT UNIQUE,
            email TEXT,
            address TEXT,
            region TEXT,
            date_joined TEXT,
            assigned_vehicle_id INTEGER,
            FOREIGN KEY (assigned_vehicle_id) REFERENCES vehicles(id)
        )
    ''')

    # Ensure existing drivers table gets the new columns if they do not exist
    cursor.execute("PRAGMA table_info(drivers)")
    existing_cols = [col[1] for col in cursor.fetchall()]
    if 'employee_id' not in existing_cols:
        cursor.execute("ALTER TABLE drivers ADD COLUMN employee_id TEXT")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_drivers_employee_id ON drivers(employee_id)")
    if 'email' not in existing_cols:
        cursor.execute("ALTER TABLE drivers ADD COLUMN email TEXT")
    if 'address' not in existing_cols:
        cursor.execute("ALTER TABLE drivers ADD COLUMN address TEXT")
    if 'region' not in existing_cols:
        cursor.execute("ALTER TABLE drivers ADD COLUMN region TEXT")
    if 'date_joined' not in existing_cols:
        cursor.execute("ALTER TABLE drivers ADD COLUMN date_joined TEXT")
    if 'assigned_vehicle_id' not in existing_cols:
        cursor.execute("ALTER TABLE drivers ADD COLUMN assigned_vehicle_id INTEGER REFERENCES vehicles(id)")

    # 4. Trips Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            destination TEXT NOT NULL,
            vehicle_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            cargo_weight REAL NOT NULL,
            planned_distance REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'Draft',
            revenue REAL NOT NULL DEFAULT 0.0,
            fuel_consumed REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dispatch_date TEXT,
            expected_return TEXT,
            actual_return TEXT,
            purpose TEXT,
            cargo_description TEXT,
            notes TEXT,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
            FOREIGN KEY (driver_id) REFERENCES drivers(id)
        )
    ''')

    # Ensure existing trips table gets the new columns if they do not exist
    cursor.execute("PRAGMA table_info(trips)")
    existing_trip_cols = [col[1] for col in cursor.fetchall()]
    if 'dispatch_date' not in existing_trip_cols:
        cursor.execute("ALTER TABLE trips ADD COLUMN dispatch_date TEXT")
    if 'expected_return' not in existing_trip_cols:
        cursor.execute("ALTER TABLE trips ADD COLUMN expected_return TEXT")
    if 'actual_return' not in existing_trip_cols:
        cursor.execute("ALTER TABLE trips ADD COLUMN actual_return TEXT")
    if 'purpose' not in existing_trip_cols:
        cursor.execute("ALTER TABLE trips ADD COLUMN purpose TEXT")
    if 'cargo_description' not in existing_trip_cols:
        cursor.execute("ALTER TABLE trips ADD COLUMN cargo_description TEXT")
    if 'notes' not in existing_trip_cols:
        cursor.execute("ALTER TABLE trips ADD COLUMN notes TEXT")

    # 5. Maintenance Logs Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS maintenance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            cost REAL NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT,
            status TEXT NOT NULL DEFAULT 'Active',
            maintenance_type TEXT,
            service_center TEXT,
            technician_name TEXT,
            scheduled_date TEXT,
            completed_date TEXT,
            estimated_cost REAL DEFAULT 0.0,
            actual_cost REAL DEFAULT 0.0,
            estimated_duration INTEGER DEFAULT 0,
            current_odometer REAL DEFAULT 0.0,
            notes TEXT,
            work_performed TEXT,
            parts_replaced TEXT,
            remarks TEXT,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
        )
    ''')

    # Ensure existing maintenance_logs table gets any new columns if they do not exist
    cursor.execute("PRAGMA table_info(maintenance_logs)")
    existing_m_cols = [col[1] for col in cursor.fetchall()]
    columns_to_add = [
        ('maintenance_type', 'TEXT'),
        ('service_center', 'TEXT'),
        ('technician_name', 'TEXT'),
        ('scheduled_date', 'TEXT'),
        ('completed_date', 'TEXT'),
        ('estimated_cost', 'REAL DEFAULT 0.0'),
        ('actual_cost', 'REAL DEFAULT 0.0'),
        ('estimated_duration', 'INTEGER DEFAULT 0'),
        ('current_odometer', 'REAL DEFAULT 0.0'),
        ('notes', 'TEXT'),
        ('work_performed', 'TEXT'),
        ('parts_replaced', 'TEXT'),
        ('remarks', 'TEXT')
    ]
    for col_name, col_type in columns_to_add:
        if col_name not in existing_m_cols:
            cursor.execute(f"ALTER TABLE maintenance_logs ADD COLUMN {col_name} {col_type}")

    # 6. Fuel Logs Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fuel_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL,
            driver_id INTEGER,
            fuel_type TEXT,
            fuel_station TEXT,
            liters REAL NOT NULL,
            price_per_liter REAL DEFAULT 0.0,
            cost REAL NOT NULL,
            odometer REAL DEFAULT 0.0,
            date TEXT NOT NULL,
            payment_method TEXT,
            remarks TEXT,
            trip_id INTEGER,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
            FOREIGN KEY (driver_id) REFERENCES drivers(id),
            FOREIGN KEY (trip_id) REFERENCES trips(id)
        )
    ''')

    # Ensure existing fuel_logs table gets any new columns if they do not exist
    cursor.execute("PRAGMA table_info(fuel_logs)")
    existing_f_cols = [col[1] for col in cursor.fetchall()]
    f_columns_to_add = [
        ('driver_id', 'INTEGER'),
        ('fuel_type', 'TEXT'),
        ('fuel_station', 'TEXT'),
        ('price_per_liter', 'REAL DEFAULT 0.0'),
        ('odometer', 'REAL DEFAULT 0.0'),
        ('payment_method', 'TEXT'),
        ('remarks', 'TEXT')
    ]
    for col_name, col_type in f_columns_to_add:
        if col_name not in existing_f_cols:
            cursor.execute(f"ALTER TABLE fuel_logs ADD COLUMN {col_name} {col_type}")

    # 7. Expenses Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            driver_id INTEGER,
            trip_id INTEGER,
            vendor TEXT,
            gst_percent REAL DEFAULT 0.0,
            gst_amount REAL DEFAULT 0.0,
            total_amount REAL DEFAULT 0.0,
            payment_method TEXT,
            status TEXT DEFAULT 'Paid',
            remarks TEXT,
            attachment TEXT,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
            FOREIGN KEY (driver_id) REFERENCES drivers(id),
            FOREIGN KEY (trip_id) REFERENCES trips(id)
        )
    ''')

    # Ensure existing expenses table gets any new columns if they do not exist
    cursor.execute("PRAGMA table_info(expenses)")
    existing_exp_cols = [col[1] for col in cursor.fetchall()]
    exp_columns_to_add = [
        ('driver_id', 'INTEGER'),
        ('trip_id', 'INTEGER'),
        ('vendor', 'TEXT'),
        ('gst_percent', 'REAL DEFAULT 0.0'),
        ('gst_amount', 'REAL DEFAULT 0.0'),
        ('total_amount', 'REAL DEFAULT 0.0'),
        ('payment_method', 'TEXT'),
        ('status', 'TEXT DEFAULT \'Paid\''),
        ('remarks', 'TEXT'),
        ('attachment', 'TEXT')
    ]
    for col_name, col_type in exp_columns_to_add:
        if col_name not in existing_exp_cols:
            cursor.execute(f"ALTER TABLE expenses ADD COLUMN {col_name} {col_type}")

    conn.commit()

    # Check and seed expenses if count is less than 25 (guarantees seed data even with existing users)
    cursor.execute('SELECT COUNT(*) FROM expenses')
    if cursor.fetchone()[0] < 25:
        cursor.execute('DELETE FROM expenses')
        expenses_seed = [
            (1, 'Fuel', 4342.50, '2026-06-01', 'Refuel 45L of Petrol', 1, 3, 'Indian Oil', 0.0, 0.0, 4342.50, 'UPI', 'Paid', 'Full tank', None),
            (2, 'Fuel', 13380.00, '2026-06-02', 'Trip refuel 150L of Diesel', 2, 1, 'Bharat Petroleum', 0.0, 0.0, 13380.00, 'Company Card', 'Paid', 'Refuel ref BP', None),
            (3, 'Fuel', 990.00, '2026-06-04', 'CNG refuel 12 kg', 3, None, 'HP Petrol Pump', 0.0, 0.0, 990.00, 'Cash', 'Paid', 'Local run', None),
            (5, 'Fuel', 7152.00, '2026-06-05', 'Diesel refuel 80L', 7, 2, 'Nayara Energy', 0.0, 0.0, 7152.00, 'UPI', 'Paid', 'Refuel before dispatch', None),
            (1, 'Maintenance', 1864.41, '2026-06-25', 'Left headlight bulb and panel fuses replacement', 1, None, 'Bosch Car Service', 18.0, 335.59, 2200.00, 'Company Card', 'Paid', 'Resolved headlight failure', None),
            (2, 'Maintenance', 4067.80, '2026-06-11', 'Front brake inspection and pads replacement', 2, None, 'Ashok Leyland Workshop', 18.0, 732.20, 4800.00, 'Bank Transfer', 'Paid', 'Completed on schedule', None),
            (1, 'Driver Salary', 25000.00, '2026-06-30', 'Monthly driver salary payout', 1, None, 'Alex Rivera', 0.0, 0.0, 25000.00, 'Bank Transfer', 'Paid', 'June 2026 Salary', None),
            (2, 'Driver Salary', 28000.00, '2026-06-30', 'Monthly driver salary payout', 2, None, 'Bob Miller', 0.0, 0.0, 28000.00, 'Bank Transfer', 'Paid', 'June 2026 Salary', None),
            (5, 'Driver Salary', 24000.00, '2026-06-30', 'Monthly driver salary payout', 7, None, 'George Costanza', 0.0, 0.0, 24000.00, 'Bank Transfer', 'Paid', 'June 2026 Salary', None),
            (1, 'Insurance', 15000.00, '2026-05-10', 'Annual Comprehensive Insurance Policy', None, None, 'HDFC Ergo Insurance', 18.0, 2700.00, 17700.00, 'Bank Transfer', 'Paid', 'Policy ID #POL-8910', None),
            (2, 'Insurance', 28000.00, '2026-05-12', 'Annual Commercial Vehicle Insurance', None, None, 'ICICI Lombard', 18.0, 5040.00, 33040.00, 'Bank Transfer', 'Paid', 'Policy ID #POL-3321', None),
            (3, 'Vehicle Registration', 5000.00, '2026-04-15', 'Registration Renewal & Green Tax', None, None, 'RTO Chennai', 0.0, 0.0, 5000.00, 'Bank Transfer', 'Paid', 'Receipt #REC-4820', None),
            (5, 'Vehicle Registration', 6500.00, '2026-04-18', 'Road Tax and Permit Renewal', None, None, 'RTO Bengaluru', 0.0, 0.0, 6500.00, 'UPI', 'Paid', 'Receipt #REC-1049', None),
            (1, 'Toll Charges', 450.00, '2026-06-01', 'NH4 Chennai-Bengaluru Toll', 1, 3, 'FASTag Toll', 0.0, 0.0, 450.00, 'UPI', 'Paid', 'Auto-debited from FASTag', None),
            (2, 'Toll Charges', 750.00, '2026-06-02', 'NH45 Toll Plaza charges', 2, 1, 'FASTag Toll', 0.0, 0.0, 750.00, 'Company Card', 'Paid', 'Auto-debited from FASTag', None),
            (3, 'Parking Fees', 150.00, '2026-06-15', 'Kochi Airport Parking Fee', 3, None, 'Airport Authority', 0.0, 0.0, 150.00, 'Cash', 'Paid', 'Official travel parking', None),
            (1, 'Parking Fees', 80.00, '2026-06-18', 'Day parking charges', 4, None, 'Metro Parking', 0.0, 0.0, 80.00, 'UPI', 'Paid', 'Local city halt', None),
            (2, 'Traffic Fines', 1000.00, '2026-06-10', 'Over-speeding fine on bypass', 2, 1, 'National Highway Police', 0.0, 0.0, 1000.00, 'UPI', 'Paid', 'Challan ID #CH-9028', None),
            (1, 'Tyre Replacement', 8474.58, '2026-05-20', 'Two front tyres replacement', 1, None, 'MRF Tyres Dealer', 18.0, 1525.42, 10000.00, 'Company Card', 'Paid', 'Replaced worn-out MRF tyres', None),
            (5, 'Tyre Replacement', 16949.15, '2026-05-25', 'Four heavy rear tyres replacement', 7, None, 'Apollo Tyres Zone', 18.0, 3050.85, 20000.00, 'Bank Transfer', 'Paid', 'Fitted high endurance tyres', None),
            (1, 'Office Expenses', 1200.00, '2026-06-12', 'Logbooks and registers for drivers', None, None, 'Local Stationery', 12.0, 144.00, 1344.00, 'Cash', 'Paid', 'Purchased driver diary pack', None),
            (1, 'Office Expenses', 3500.00, '2026-06-14', 'Office printing ink and paper bundles', None, None, 'Staples Dealer', 18.0, 630.00, 4130.00, 'UPI', 'Paid', 'Quarterly office supplies', None),
            (3, 'Miscellaneous', 500.00, '2026-06-22', 'Interior cleaning and disinfection', 3, None, 'Local Workshop', 0.0, 0.0, 500.00, 'Cash', 'Paid', 'Post-trip sanitize', None),
            (5, 'Miscellaneous', 800.00, '2026-06-23', 'Detailed exterior washing', 7, None, 'Express Wash', 18.0, 144.00, 944.00, 'UPI', 'Pending', 'Awaiting washing clearance', None),
            (2, 'Miscellaneous', 1200.00, '2026-06-03', 'Unapproved minor repair on trip', 2, 1, 'Local workshop', 0.0, 0.0, 1200.00, 'Cash', 'Cancelled', 'Claim rejected by manager', None)
        ]
        cursor.executemany('''
            INSERT INTO expenses (vehicle_id, type, amount, date, description, driver_id, trip_id, vendor, gst_percent, gst_amount, total_amount, payment_method, status, remarks, attachment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', expenses_seed)
        conn.commit()

    # Check and seed fuel logs if count is less than 10 (guarantees seed data even with existing users)
    cursor.execute('SELECT COUNT(*) FROM fuel_logs')
    if cursor.fetchone()[0] < 10:
        cursor.execute('DELETE FROM fuel_logs')
        fuel_data = [
            (1, 1, 'Petrol', 'Indian Oil', 45.0, 96.50, 4342.50, 10000.0, '2026-06-01 08:30', 'UPI', 'Full tank', None),
            (2, 2, 'Diesel', 'Bharat Petroleum', 150.0, 89.20, 13380.00, 78000.0, '2026-06-02 10:15', 'Company Account', 'Trip refuel', None),
            (3, 3, 'CNG', 'HP Petrol Pump', 12.0, 82.50, 990.00, 41000.0, '2026-06-04 14:00', 'Cash', 'Local travel', None),
            (5, 7, 'Diesel', 'Nayara Energy', 80.0, 89.40, 7152.00, 48000.0, '2026-06-05 17:45', 'Credit Card', 'Scheduled', None),
            (1, 1, 'Petrol', 'Shell India', 42.0, 102.40, 4300.80, 10500.0, '2026-06-10 09:00', 'UPI', 'Regular fill', None),
            (2, 2, 'Diesel', 'Indian Oil', 160.0, 89.50, 14320.00, 79200.0, '2026-06-12 11:30', 'Company Account', 'Bulk fuel', None),
            (3, 3, 'Electric Charging', 'Tata Power EZ Charge', 35.0, 15.00, 525.00, 41800.0, '2026-06-15 16:20', 'UPI', 'Full charge', None),
            (5, 7, 'Diesel', 'HP Petrol Pump', 85.0, 89.60, 7616.00, 49200.0, '2026-06-18 07:15', 'Credit Card', 'Fleet card', None),
            (1, 1, 'Petrol', 'HP Petrol Pump', 44.0, 96.20, 4232.80, 11000.0, '2026-06-20 18:30', 'Credit Card', '', None),
            (2, 2, 'Diesel', 'Shell India', 155.0, 94.80, 14694.00, 80500.0, '2026-06-22 13:00', 'Company Account', 'Shell premium diesel', None),
            (3, 3, 'CNG', 'Indian Oil', 14.0, 82.50, 1155.00, 42500.0, '2026-06-25 10:45', 'Cash', '', None),
            (5, 7, 'Diesel', 'Bharat Petroleum', 82.0, 89.10, 7306.20, 50300.0, '2026-06-26 12:00', 'UPI', 'Routine check', None),
            (1, 1, 'Petrol', 'Indian Oil', 46.0, 96.00, 4416.00, 11550.0, '2026-07-01 08:00', 'UPI', 'Monthly start', None),
            (2, 2, 'Diesel', 'Nayara Energy', 150.0, 89.30, 13395.00, 81800.0, '2026-07-02 15:30', 'Company Account', '', None),
            (3, 3, 'Electric Charging', 'Fortum Charge', 38.0, 15.00, 570.00, 43200.0, '2026-07-03 14:15', 'Credit Card', 'Charge', None),
            (5, 7, 'Diesel', 'Indian Oil', 88.0, 89.00, 7832.00, 51500.0, '2026-07-05 09:45', 'Company Account', '', None),
            (1, 1, 'Petrol', 'Bharat Petroleum', 43.0, 95.80, 4119.40, 12050.0, '2026-07-07 19:10', 'Cash', '', None),
            (2, 2, 'Diesel', 'HP Petrol Pump', 165.0, 89.70, 14800.50, 83100.0, '2026-07-08 11:00', 'Company Account', '', None),
            (3, 3, 'CNG', 'Bharat Petroleum', 13.0, 82.50, 1072.50, 44000.0, '2026-07-09 16:00', 'UPI', '', None),
            (5, 7, 'Diesel', 'Shell India', 84.0, 94.50, 7938.00, 52600.0, '2026-07-10 08:30', 'Credit Card', 'Premium diesel', None)
        ]
        cursor.executemany('''
            INSERT INTO fuel_logs (vehicle_id, driver_id, fuel_type, fuel_station, liters, price_per_liter, cost, odometer, date, payment_method, remarks, trip_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', fuel_data)
        
        # Seed fuel expenses
        for item in fuel_data:
            cursor.execute("""
                INSERT INTO expenses (vehicle_id, type, amount, date, description)
                VALUES (?, 'Fuel', ?, ?, ?)
            """, (item[0], item[6], item[8][:10], f"Refuel at {item[3]}: {item[4]}L of {item[2]} (FL-seeded)"))
        conn.commit()

    # Check if we need to seed data (e.g., if users table is empty)
    cursor.execute('SELECT COUNT(*) FROM users')
    if cursor.fetchone()[0] == 0:
        seed_data(conn)

    conn.close()

def seed_data(conn):
    cursor = conn.cursor()

    # Seed Users
    users_data = [
        ('Fleet Manager', 'manager@transitops.com', hash_password('password123'), 'Fleet Manager'),
        ('Driver Alex', 'driver@transitops.com', hash_password('password123'), 'Driver'),
        ('Safety Officer', 'safety@transitops.com', hash_password('password123'), 'Safety Officer'),
        ('Financial Analyst', 'finance@transitops.com', hash_password('password123'), 'Financial Analyst')
    ]
    cursor.executemany('INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)', users_data)

    # Seed Vehicles
    vehicles_data = [
        ('Van-05', 'Ford Transit 2023', 'Van', 500.0, 12500.0, 25000.0, 'Available', 'North'),
        ('Truck-12', 'Volvo FH16 Heavy', 'Heavy Truck', 5000.0, 84000.0, 65000.0, 'On Trip', 'East'),
        ('Sedan-01', 'Toyota Prius', 'Sedan', 350.0, 45000.0, 18000.0, 'In Shop', 'South'),
        ('Van-02', 'Mercedes Sprinter', 'Van', 600.0, 110000.0, 22000.0, 'Retired', 'West'),
        ('Truck-03', 'Isuzu NPR Medium', 'Medium Truck', 3000.0, 54000.0, 48000.0, 'On Trip', 'North')
    ]
    cursor.executemany('''
        INSERT INTO vehicles (registration_number, name, type, max_load_capacity, odometer, acquisition_cost, status, region)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', vehicles_data)

    # Seed Drivers (10 realistic drivers matching business statuses and regions)
    drivers_data = [
        ('Alex Rivera', 'LIC-98234', 'Heavy Commercial', '2027-12-31', '5550101', 95.0, 'Available', 'EMP-001', 'alex.rivera@transitops.com', '789 Pine Rd, North City', 'North', '2023-01-15', 1),
        ('Bob Miller', 'LIC-45678', 'HMV', '2026-09-15', '5550102', 88.0, 'On Trip', 'EMP-002', 'bob.miller@transitops.com', '456 Oak Ave, East Town', 'East', '2023-04-20', 2),
        ('Charlie Davis', 'LIC-11223', 'LMV', '2025-05-20', '5550103', 72.0, 'On Leave', 'EMP-003', 'charlie.davis@transitops.com', '12 Apple St, South Beach', 'South', '2024-02-10', None),
        ('David Clark', 'LIC-44556', 'Heavy Commercial', '2028-01-10', '5550104', 99.0, 'Inactive', 'EMP-004', 'david.clark@transitops.com', '101 Cedar Ln, West Hills', 'West', '2022-11-05', None),
        ('Ethan Hunt', 'LIC-55667', 'Trailer', '2028-11-30', '5550105', 96.5, 'Available', 'EMP-005', 'ethan.hunt@transitops.com', '321 Mission Way, North City', 'North', '2025-01-01', None),
        ('Fiona Gallagher', 'LIC-66778', 'LMV', '2027-06-15', '5550106', 91.0, 'Available', 'EMP-006', 'fiona.g@transitops.com', '550 Southside Blvd, South Beach', 'South', '2025-03-12', None),
        ('George Costanza', 'LIC-77889', 'HMV', '2026-10-24', '5550107', 82.5, 'On Trip', 'EMP-007', 'george.c@transitops.com', '84 Fifth Ave, Central Park', 'Central', '2024-08-15', 5),
        ('Hannah Abbott', 'LIC-88990', 'Trailer', '2029-04-12', '5550108', 97.0, 'Available', 'EMP-008', 'hannah.a@transitops.com', '23 Hogsmeade Rd, West Hills', 'West', '2023-10-30', None),
        ('Ian Malcolm', 'LIC-99001', 'Heavy Commercial', '2028-08-08', '5550109', 93.0, 'On Leave', 'EMP-009', 'ian.m@transitops.com', '45 Park Ave, East Town', 'East', '2024-11-18', None),
        ('Julia Roberts', 'LIC-10102', 'LMV', '2027-02-28', '5550110', 89.0, 'Inactive', 'EMP-010', 'julia.r@transitops.com', '123 Hollywood Blvd, West Hills', 'West', '2022-05-20', None)
    ]
    cursor.executemany('''
        INSERT INTO drivers (name, license_number, license_category, license_expiry_date, contact_number, safety_score, status, employee_id, email, address, region, date_joined, assigned_vehicle_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', drivers_data)

    # Seed Trips (15 realistic Indian logistics trips)
    trips_data = [
        ('Chennai', 'Bengaluru', 2, 2, 4000.0, 350.0, 'In Progress', 12000.0, None, '2026-07-11 08:00', '2026-07-12 18:00', None, 'Delivery', 'Automotive Parts', 'Careful with cargo alignment.'),
        ('Hyderabad', 'Vijayawada', 5, 7, 1500.0, 275.0, 'In Progress', 8500.0, None, '2026-07-11 10:00', '2026-07-12 14:00', None, 'Express', 'Pharmaceuticals', 'Store in temperature-controlled zone.'),
        ('Coimbatore', 'Kochi', 1, 1, 450.0, 190.0, 'Completed', 5000.0, 22.0, '2026-07-09 06:00', '2026-07-09 18:00', '2026-07-09 17:30', 'Delivery', 'Textiles', 'Delivered on time.'),
        ('Mumbai', 'Pune', 1, 6, 300.0, 150.0, 'Completed', 4200.0, 18.0, '2026-07-08 09:00', '2026-07-08 15:00', '2026-07-08 14:45', 'Urgent', 'Electronics', 'No damage reported.'),
        ('Delhi', 'Jaipur', 5, 5, 2200.0, 270.0, 'Completed', 9000.0, 35.0, '2026-07-07 07:00', '2026-07-07 19:00', '2026-07-07 18:30', 'Delivery', 'Handicrafts', 'Completed successfully.'),
        ('Bengaluru', 'Mysuru', 1, 1, 400.0, 145.0, 'Scheduled', 0.0, None, '2026-07-13 06:00', '2026-07-13 12:00', None, 'Delivery', 'Fresh Produce', 'Needs to be dispatched early morning.'),
        ('Ahmedabad', 'Vadodara', 5, 8, 2500.0, 110.0, 'Scheduled', 0.0, None, '2026-07-14 08:00', '2026-07-14 14:00', None, 'Delivery', 'Industrial Chemicals', 'Driver is certified for chemical carriage.'),
        ('Kolkata', 'Haldia', 2, 2, 4800.0, 125.0, 'Completed', 6500.0, 42.0, '2026-07-05 05:00', '2026-07-05 15:00', '2026-07-05 16:15', 'Regular', 'Industrial Machinery', 'Delayed slightly due to port traffic.'),
        ('Lucknow', 'Kanpur', 1, 5, 350.0, 90.0, 'Cancelled', 0.0, None, '2026-07-06 10:00', '2026-07-06 14:00', None, 'Regular', 'Leather Goods', 'Cancelled due to heavy rain and road blockage.'),
        ('Mumbai', 'Nashik', 5, 6, 1800.0, 170.0, 'Cancelled', 0.0, None, '2026-07-04 08:00', '2026-07-04 16:00', None, 'Delivery', 'Agricultural Equipment', 'Client rescheduled shipment delivery.'),
        ('Chennai', 'Madurai', 2, 2, 3800.0, 460.0, 'Completed', 15000.0, 140.0, '2026-07-02 22:00', '2026-07-03 10:00', '2026-07-03 09:45', 'Delivery', 'Foodstuffs', 'Long haul completed ahead of schedule.'),
        ('Hyderabad', 'Warangal', 1, 1, 480.0, 150.0, 'Completed', 4500.0, 17.0, '2026-06-30 08:00', '2026-06-30 14:00', '2026-06-30 13:50', 'Contract', 'Electrical Cables', 'Handed over to site engineer.'),
        ('Pune', 'Kolhapur', 5, 8, 2100.0, 235.0, 'Completed', 8800.0, 31.0, '2026-06-28 07:00', '2026-06-28 17:00', '2026-06-28 16:30', 'Regular', 'Engineering Spares', 'Smooth drive via NH4.'),
        ('Delhi', 'Agra', 1, 6, 250.0, 230.0, 'Completed', 5200.0, 21.0, '2026-06-25 09:00', '2026-06-25 16:00', '2026-06-25 15:45', 'Marketing', 'Promotional Materials', 'Delivered to hotel venue.'),
        ('Kochi', 'Trivandrum', 2, 2, 4100.0, 200.0, 'Cancelled', 0.0, None, '2026-07-01 04:00', '2026-07-01 11:00', None, 'Delivery', 'Seafood', 'Refrigerator unit failure before departure.')
    ]
    cursor.executemany('''
        INSERT INTO trips (source, destination, vehicle_id, driver_id, cargo_weight, planned_distance, status, revenue, fuel_consumed, dispatch_date, expected_return, actual_return, purpose, cargo_description, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', trips_data)

    # Seed Maintenance Logs
    cursor.execute('SELECT COUNT(*) FROM maintenance_logs')
    if cursor.fetchone()[0] < 5:
        cursor.execute('DELETE FROM maintenance_logs')
        maintenance_data = [
            (1, 'Routine replacement of front tyres due to thread wear.', 0.0, '2026-07-15', None, 'Scheduled', 'Tyre Replacement', 'TVS Vehicle Care', 'Rajesh K.', '2026-07-15', None, 12000.0, 0.0, 1, 12500.0, 'Ensure wheel alignment is done.', None, None, None),
            (2, 'Front brake inspection and pads replacement.', 4800.0, '2026-06-10', '2026-06-11', 'Completed', 'Brake Inspection', 'Ashok Leyland Workshop', 'Amit Kumar', '2026-06-10', '2026-06-11', 4500.0, 4800.0, 1, 82000.0, 'Squeaking noise reported by driver.', 'Replaced front brake pads and bleed lines.', 'Front Brake Pads', 'Completed on time.'),
            (3, 'Engine check light diagnostics.', 0.0, '2026-07-10', None, 'In Progress', 'Engine Service', 'Mahindra First Choice', 'Suresh Patel', '2026-07-10', None, 8500.0, 0.0, 3, 44800.0, 'Check engine light and loss of power.', 'Diagnostic scans and cylinder check ongoing.', None, None),
            (5, 'Periodic service and multi-point safety inspection.', 0.0, '2026-07-05', None, 'Overdue', 'General Service', 'Tata Motors Service Centre', 'Ramesh Sharma', '2026-07-05', None, 15000.0, 0.0, 2, 53500.0, 'Mandatory 50,000 km service.', None, None, 'Service overdue due to asset scheduling conflict.'),
            (1, 'AC compressor check and cooling gas top up.', 0.0, '2026-07-01', '2026-07-01', 'Cancelled', 'AC Service', 'Bosch Car Service', 'Anil Mehta', '2026-07-01', '2026-07-01', 3500.0, 0.0, 1, 12000.0, 'AC not cooling effectively.', None, None, 'Cancelled - vehicle rescheduled for high priority trip.'),
            (2, 'Engine oil change and filter replacements.', 7500.0, '2026-05-15', '2026-05-15', 'Completed', 'Oil Change', 'Ashok Leyland Workshop', 'Harpreet Singh', '2026-05-15', '2026-05-15', 7500.0, 7500.0, 1, 79500.0, 'Scheduled lube service.', 'Replaced engine oil and oil filter.', 'Oil Filter, 15W40 Lube', 'Smooth and quick service.'),
            (3, 'Weak self-start battery test and replacement.', 5800.0, '2026-04-20', '2026-04-20', 'Completed', 'Battery Check', 'Bosch Car Service', 'Manoj Tiwari', '2026-04-20', '2026-04-20', 6000.0, 5800.0, 1, 42000.0, 'Vehicle self-start lagging.', 'Replaced old battery with new Exide Battery.', 'Exide Heavy Duty Battery', 'Replaced under warranty discount.'),
            (5, 'Rear leaf spring suspension bush replacement.', 19500.0, '2026-03-12', '2026-03-14', 'Completed', 'Suspension', 'TVS Vehicle Care', 'Vijay Iyer', '2026-03-12', '2026-03-14', 18000.0, 19500.0, 2, 48000.0, 'Squeaking rear suspension and alignment issue.', 'Installed heavy duty leaf bushings and new shock absorbers.', 'Shock Absorbers, Suspension Bushes', 'Fully resolved, ride quality restored.'),
            (1, 'Blown headlight bulb and dashboard illumination.', 2200.0, '2026-06-25', '2026-06-25', 'Completed', 'Electrical', 'Bosch Car Service', 'Vinod Nair', '2026-06-25', '2026-06-25', 2500.0, 2200.0, 1, 11800.0, 'Left headlight not working.', 'Replaced left headlight halogen bulb and panel fuses.', 'Halogen Bulb, 15A Fuses', 'Tested okay.'),
            (2, 'Cabin air filter and mechanical lock check.', 0.0, '2026-07-20', None, 'Scheduled', 'Other', 'Ashok Leyland Workshop', 'Jaspreet Singh', '2026-07-20', None, 5000.0, 0.0, 1, 84000.0, 'Routine cabin inspection.', None, None, None),
            (3, 'AC duct cleaning and vent grill replacement.', 0.0, '2026-06-01', '2026-06-01', 'Cancelled', 'AC Service', 'Mahindra First Choice', 'Rajesh Rao', '2026-06-01', '2026-06-01', 4000.0, 0.0, 1, 43000.0, 'Foul smell from AC vents.', None, None, 'Cancelled due to driver on leave.'),
            (5, 'Brake drum cleaning and adjustment.', 5500.0, '2026-02-10', '2026-02-10', 'Completed', 'Brake Inspection', 'Tata Motors Service Centre', 'Sunil Dutt', '2026-02-10', '2026-02-10', 5500.0, 5500.0, 1, 45000.0, 'Brake play adjustment required.', 'Cleaned brake drum liner and adjusted clearance.', 'None', 'Braking performance restored.'),
            (1, 'Standard 10,000 km general fluid service.', 9400.0, '2026-01-15', '2026-01-16', 'Completed', 'General Service', 'TVS Vehicle Care', 'Kumar Swamy', '2026-01-15', '2026-01-16', 9000.0, 9400.0, 2, 8500.0, 'First major comprehensive service.', 'Topped up all fluid levels, replaced air filter.', 'Air Filter', 'First general service logged.'),
            (2, 'Major engine tuning and coolant overhaul.', 21500.0, '2025-12-10', '2025-12-12', 'Completed', 'General Service', 'TVS Vehicle Care', 'Mohan Lal', '2025-12-10', '2025-12-12', 22000.0, 21500.0, 2, 72000.0, 'Yearly heavy maintenance scheduled.', 'Flushed engine cooling lines, refilled coolant, tuned engine injectors.', 'Engine Coolant, Primary Fuel Filter', 'Performance improved significantly.'),
            (3, 'Rear tyre replacement.', 0.0, '2026-07-02', None, 'Overdue', 'Tyre Replacement', 'Mahindra First Choice', 'Kedar Shinde', '2026-07-02', None, 16000.0, 0.0, 1, 44500.0, 'Rear tyres thread depth below 2mm.', None, None, 'Awaiting approval for procurement.')
        ]
        cursor.executemany('''
            INSERT INTO maintenance_logs (vehicle_id, description, cost, start_date, end_date, status, maintenance_type, service_center, technician_name, scheduled_date, completed_date, estimated_cost, actual_cost, estimated_duration, current_odometer, notes, work_performed, parts_replaced, remarks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', maintenance_data)

    # Seed Fuel Logs
    cursor.execute('SELECT COUNT(*) FROM fuel_logs')
    if cursor.fetchone()[0] < 10:
        cursor.execute('DELETE FROM fuel_logs')
        fuel_data = [
            (1, 1, 'Petrol', 'Indian Oil', 45.0, 96.50, 4342.50, 10000.0, '2026-06-01 08:30', 'UPI', 'Full tank', None),
            (2, 2, 'Diesel', 'Bharat Petroleum', 150.0, 89.20, 13380.00, 78000.0, '2026-06-02 10:15', 'Company Account', 'Trip refuel', None),
            (3, 3, 'CNG', 'HP Petrol Pump', 12.0, 82.50, 990.00, 41000.0, '2026-06-04 14:00', 'Cash', 'Local travel', None),
            (5, 7, 'Diesel', 'Nayara Energy', 80.0, 89.40, 7152.00, 48000.0, '2026-06-05 17:45', 'Credit Card', 'Scheduled', None),
            (1, 1, 'Petrol', 'Shell India', 42.0, 102.40, 4300.80, 10500.0, '2026-06-10 09:00', 'UPI', 'Regular fill', None),
            (2, 2, 'Diesel', 'Indian Oil', 160.0, 89.50, 14320.00, 79200.0, '2026-06-12 11:30', 'Company Account', 'Bulk fuel', None),
            (3, 3, 'Electric Charging', 'Tata Power EZ Charge', 35.0, 15.00, 525.00, 41800.0, '2026-06-15 16:20', 'UPI', 'Full charge', None),
            (5, 7, 'Diesel', 'HP Petrol Pump', 85.0, 89.60, 7616.00, 49200.0, '2026-06-18 07:15', 'Credit Card', 'Fleet card', None),
            (1, 1, 'Petrol', 'HP Petrol Pump', 44.0, 96.20, 4232.80, 11000.0, '2026-06-20 18:30', 'Credit Card', '', None),
            (2, 2, 'Diesel', 'Shell India', 155.0, 94.80, 14694.00, 80500.0, '2026-06-22 13:00', 'Company Account', 'Shell premium diesel', None),
            (3, 3, 'CNG', 'Indian Oil', 14.0, 82.50, 1155.00, 42500.0, '2026-06-25 10:45', 'Cash', '', None),
            (5, 7, 'Diesel', 'Bharat Petroleum', 82.0, 89.10, 7306.20, 50300.0, '2026-06-26 12:00', 'UPI', 'Routine check', None),
            (1, 1, 'Petrol', 'Indian Oil', 46.0, 96.00, 4416.00, 11550.0, '2026-07-01 08:00', 'UPI', 'Monthly start', None),
            (2, 2, 'Diesel', 'Nayara Energy', 150.0, 89.30, 13395.00, 81800.0, '2026-07-02 15:30', 'Company Account', '', None),
            (3, 3, 'Electric Charging', 'Fortum Charge', 38.0, 15.00, 570.00, 43200.0, '2026-07-03 14:15', 'Credit Card', 'Charge', None),
            (5, 7, 'Diesel', 'Indian Oil', 88.0, 89.00, 7832.00, 51500.0, '2026-07-05 09:45', 'Company Account', '', None),
            (1, 1, 'Petrol', 'Bharat Petroleum', 43.0, 95.80, 4119.40, 12050.0, '2026-07-07 19:10', 'Cash', '', None),
            (2, 2, 'Diesel', 'HP Petrol Pump', 165.0, 89.70, 14800.50, 83100.0, '2026-07-08 11:00', 'Company Account', '', None),
            (3, 3, 'CNG', 'Bharat Petroleum', 13.0, 82.50, 1072.50, 44000.0, '2026-07-09 16:00', 'UPI', '', None),
            (5, 7, 'Diesel', 'Shell India', 84.0, 94.50, 7938.00, 52600.0, '2026-07-10 08:30', 'Credit Card', 'Premium diesel', None)
        ]
        cursor.executemany('''
            INSERT INTO fuel_logs (vehicle_id, driver_id, fuel_type, fuel_station, liters, price_per_liter, cost, odometer, date, payment_method, remarks, trip_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', fuel_data)

    # Seed Expenses
    expenses_data = [
        (2, 'Toll', 45.0, '2026-07-10', 'Highway Toll'),
        (3, 'Maintenance', 350.0, '2026-07-10', 'Engine Diagnostics and Oil Change'),
        (1, 'Fuel', 30.0, '2026-07-09', 'Refuel')
    ]
    cursor.executemany('''
        INSERT INTO expenses (vehicle_id, type, amount, date, description)
        VALUES (?, ?, ?, ?, ?)
    ''', expenses_data)

    conn.commit()

if __name__ == '__main__':
    init_db()
    print("Database initialized and seeded.")
