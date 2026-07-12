# 🚛 TransitOps – Fleet Management & Live Telemetry System

Note: For email and password go down

TransitOps is a comprehensive, full-stack Fleet Management and Live Telemetry platform developed for **Odoo Hackathon 2026**. It enables organizations to efficiently manage vehicles, drivers, trips, maintenance, fuel consumption, operational expenses, and business analytics through a secure Role-Based Access Control (RBAC) system.

The platform provides real-time operational visibility with interactive dashboards, live route tracking, automated business validations, and analytics-driven decision making.

---

# ✨ Key Features

## 🔐 Authentication & Role-Based Access Control (RBAC)

- Secure email/password authentication
- Session-based access control
- Role-Based Access Control (RBAC)
- Protected routes for authenticated users only

Supported Roles:

- Fleet Manager
- Safety Officer
- Financial Analyst
- Driver

---

## 📊 Dashboard

- Live operational KPIs
- Active Vehicles
- Available Vehicles
- Vehicles In Maintenance
- Active Trips
- Pending Trips
- Drivers On Duty
- Fleet Utilization

Filters:

- Vehicle Type
- Vehicle Status
- Region

---

## 🚚 Vehicle Management

- Vehicle Registry
- Vehicle CRUD
- Capacity Management
- Odometer Tracking
- Acquisition Cost
- Vehicle Status Management

Supported Statuses:

- Available
- On Trip
- In Shop
- Retired

---

## 👨‍✈️ Driver Management

- Driver Profiles
- License Management
- License Expiry Tracking
- Contact Information
- Safety Score
- Vehicle Assignment
- Driver Availability

Supported Statuses:

- Available
- On Trip
- Off Duty
- Suspended

---

## 🛣️ Trip Management

- Dispatch Planning
- Vehicle Assignment
- Driver Assignment
- Cargo Validation
- Planned Distance Tracking
- Route Management

Trip Lifecycle

- Draft
- Dispatched
- Completed
- Cancelled

Business Rules

- Driver cannot be assigned to multiple active trips.
- Vehicle cannot exceed maximum load capacity.
- Return date cannot precede dispatch date.
- Vehicles in maintenance cannot be dispatched.

---

## 📍 Live GPS Tracking

- Interactive Leaflet Maps
- Live Route Visualization
- Dynamic Route Rendering
- Automatic Map Zoom
- Route Telemetry
- Driver Tracking
- Vehicle Tracking

Supported Indian logistics hubs include automatic coordinate lookup with OpenStreetMap integration.

---

## 🔧 Maintenance Management

- Maintenance Scheduling
- Vehicle Service History
- Workshop Tracking
- Cost Tracking
- Maintenance Intelligence

Business Rule:

Creating a maintenance record immediately changes the vehicle status to **In Shop**, preventing it from being assigned to new trips.

---

## ⛽ Fuel Management

- Fuel Log Registry
- Fuel Cost Tracking
- Fuel Efficiency Analytics
- Vehicle-wise Fuel History

---

## 💰 Expense Management

Track:

- Fuel Expenses
- Driver Salaries
- Toll Charges
- Parking Charges
- Maintenance Costs
- Miscellaneous Expenses

Automatically computes operational cost per vehicle.

---

## 📈 Reports & Analytics

Business Intelligence dashboards include:

- Fuel Efficiency
- Fleet Utilization
- Operational Costs
- Vehicle ROI
- Maintenance Analytics
- Expense Analytics

Vehicle ROI Formula:

```
ROI = (Revenue − (Maintenance + Fuel)) / Acquisition Cost
```

Exports:

- CSV Export
- Print-Friendly Reports

---

## 🌙 User Experience

- Responsive Bootstrap 5 UI
- Dark Mode
- Interactive Charts
- Responsive Tables
- Live KPI Cards
- Toast Notifications
- Validation Modals

---

# 🛠 Tech Stack

## Backend

- Python
- Flask
- SQLite

## Frontend

- HTML5
- CSS3
- Bootstrap 5
- JavaScript
- Vite

## Mapping

- Leaflet.js
- OpenStreetMap
- Nominatim Geocoder

## Version Control

- Git
- GitHub

---

# 📂 Project Structure

```
TransitOps
│
├── app.py
├── database.py
├── transitops.db
├── requirements.txt
├── package.json
├── README.md
│
├── static/
├── templates/
├── src/
```

---

# ⚙️ Installation

## 1. Clone Repository

```bash
git clone <repository-url>
cd TransitOps
```

---

## 2. Create Virtual Environment

Windows

```bash
python -m venv venv
venv\Scripts\activate
```

macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Install Frontend Dependencies

```bash
npm install
```

---

## 5. Run Backend

```bash
python app.py
```

---

## 6. Run Frontend

```bash
npm run dev
```

---

# 👥 Demo Credentials & Role Access

Use the following demo accounts to explore TransitOps with different user roles and permissions.

| Profile Role | Email | Password | Dashboard Views | Restricted Access |
|--------------|-------|----------|-----------------|-------------------|
| **Fleet Manager** | `manager@transitops.in` | `password123` | Global Operations Control Center | None (Full Access) |
| **Safety Officer** | `safety@transitops.in` | `password123` | Dashboard, Vehicles, Drivers, Maintenance, Fuel (Read-only), Reports | Trips, Expenses |
| **Financial Analyst 1** | `finance1@transitops.in` | `password123` | Dashboard, Fuel, Expenses, Reports | Drivers, Trips, Maintenance (Editing) |
| **Financial Analyst 2** | `finance2@transitops.in` | `password123` | Dashboard, Fuel, Expenses, Reports | Drivers, Trips, Maintenance (Editing) |
| **Driver 1 (Aarav Sharma)** | `driver1@transitops.in` | `password123` | Dashboard, My Profile, Assigned Vehicle, My Trips | Fuel, Maintenance, Expenses, Reports |
| **Driver 2 (Alex Rivera)** | `driver2@transitops.in` | `password123` | Dashboard, My Profile, Assigned Vehicle, My Trips | Fuel, Maintenance, Expenses, Reports |
| **Driver 3 (Vikram Singh)** | `driver3@transitops.in` | `password123` | Dashboard, My Profile, Assigned Vehicle, My Trips | Fuel, Maintenance, Expenses, Reports |
| **Driver 4 (Amit Patel)** | `driver4@transitops.in` | `password123` | Dashboard, My Profile, Assigned Vehicle, My Trips | Fuel, Maintenance, Expenses, Reports |

---

# 🔐 Role-Based Access Control

TransitOps enforces strict Role-Based Access Control (RBAC).

### Fleet Manager

- Complete administrative access
- Fleet operations
- Vehicle management
- Driver management
- Trip dispatch
- Maintenance
- Fuel
- Expenses
- Reports

---

### Safety Officer

- Dashboard
- Vehicles
- Drivers
- Maintenance
- Fuel (Read-only)
- Reports

No access to:

- Trips
- Expenses

---

### Financial Analyst

- Dashboard
- Fuel
- Expenses
- Reports

No access to:

- Drivers
- Trips
- Maintenance editing

---

### Driver

- Dashboard
- My Profile
- Assigned Vehicle
- My Trips

No access to:

- Fuel
- Maintenance
- Expenses
- Reports

---

# ✅ Core Business Rules

TransitOps enforces enterprise-grade operational constraints.

- Only authenticated users can access protected modules.
- Unauthorized users cannot access restricted routes.
- Driver assignments are one-to-one.
- Vehicle assignments are one-to-one.
- Vehicles under maintenance cannot be dispatched.
- Drivers already on active trips cannot receive another dispatch.
- Cargo weight cannot exceed vehicle capacity.
- Dispatch return date cannot precede departure.
- Vehicle operational cost is automatically calculated.
- Fleet KPIs update dynamically after CRUD operations.

---

# 🚀 Demo Flow

1. Login as Fleet Manager.
2. View Dashboard KPIs.
3. Manage Vehicles.
4. Manage Drivers.
5. Create a Dispatch Order.
6. Track Live Route.
7. Record Fuel.
8. Schedule Maintenance.
9. Record Expenses.
10. Generate Reports.

---

# 👨‍💻 Team

**Project:** TransitOps – Fleet Management & Live Telemetry System

**Developed for:** Odoo Hackathon 2026

### Team Members

- Rishi Ravichandar
- <Teammate Name>

---

# 📄 License

This project was developed exclusively for the **Odoo Hackathon 2026** as a demonstration of a modern fleet management and live telemetry platform.