# Parent Portal - Student Monitor

A separate Flask application that allows parents to view their children's academic progress, including grades and attendance records.

## Features

- **Parent Registration & Login**: Secure authentication system for parents
- **Student Dashboard**: Overview of all children linked to the parent account
- **Grade Tracking**: View detailed grade reports by subject, period, and school year
- **Attendance Monitoring**: Track attendance patterns and statistics
- **Profile Management**: Update personal information and change passwords
- **Responsive Design**: Mobile-friendly interface

## System Architecture

The parent portal is a separate Flask application (`parent_app.py`) that runs independently from the main teacher/admin system. It uses the same database but has its own tables for parent and student data.

### Database Tables

- **parents**: Parent account information
- **students**: Student information linked to parents
- **student_grades**: Grade records for students
- **student_attendance**: Attendance records for students

## Installation & Setup

### 1. Prerequisites

Make sure you have the main Student Monitor system running and the database configured.

### 2. Install Dependencies

The parent portal uses the same dependencies as the main system. Make sure you have:

```bash
pip install flask sqlalchemy psycopg2-binary python-dotenv werkzeug
```

### 3. Environment Variables

Create a `.env` file in the project root with:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/student_monitor
PARENT_FLASK_SECRET_KEY=your_secret_key_here
```

### 4. Run the Parent Portal

```bash
python parent_app.py
```

The parent portal will run on `http://localhost:5001` (different port from the main app).

## Usage

### For Parents

1. **Register**: Visit the parent portal and create an account
2. **Login**: Use your credentials to access the dashboard
3. **View Children**: See all children linked to your account
4. **Monitor Progress**: Check grades and attendance for each child
5. **Update Profile**: Manage your account information

### For Administrators

1. **Link Students**: Use the main system to link students to parent accounts
2. **Sync Data**: Transfer grades and attendance data to the parent portal
3. **Manage Access**: Control which parents can access which students

## File Structure

```
Student-Monitor/
├── parent_app.py                 # Main parent portal application
├── parent_templates/             # HTML templates for parent portal
│   ├── parent_base.html         # Base template with navigation
│   ├── parent_index.html        # Landing page
│   ├── parent_login.html        # Login page
│   ├── parent_register.html     # Registration page
│   ├── parent_dashboard.html    # Main dashboard
│   ├── student_details.html     # Individual student view
│   └── parent_profile.html      # Profile management
├── static/css/
│   └── parent_style.css         # Styling for parent portal
└── populate_parent_data.py      # Script to create sample data
```

## API Endpoints

### Authentication
- `GET /` - Landing page
- `GET /parent/register` - Registration form
- `POST /parent/register` - Create parent account
- `GET /parent/login` - Login form
- `POST /parent/login` - Authenticate parent
- `GET /parent/logout` - Logout

### Dashboard & Student Management
- `GET /parent/dashboard` - Main dashboard
- `GET /parent/student/<id>` - Student details
- `GET /parent/student/<id>/grades` - Student grades
- `GET /parent/student/<id>/attendance` - Student attendance
- `GET /parent/profile` - Profile management
- `POST /parent/profile` - Update profile

## Security Features

- **Password Hashing**: All passwords are securely hashed
- **Session Management**: Secure session handling
- **Access Control**: Parents can only view their own children's data
- **Input Validation**: All form inputs are validated
- **SQL Injection Protection**: Uses SQLAlchemy ORM

## Sample Data

To populate the system with sample data for testing:

```bash
python populate_parent_data.py
```

This will create:
- 3 sample parents with login credentials
- 4 sample students linked to parents
- Sample grades and attendance records

### Sample Login Credentials

- Username: `parent1`, Password: `password123`
- Username: `parent2`, Password: `password123`
- Username: `parent3`, Password: `password123`

## Integration with Main System

The parent portal is designed to work alongside the main teacher/admin system. To integrate:

1. **Data Synchronization**: Create a script to sync student data from the main system
2. **User Management**: Link parent accounts to student records
3. **Real-time Updates**: Set up automated data transfer for grades and attendance

## Customization

### Styling
Modify `static/css/parent_style.css` to customize the appearance.

### Templates
Edit files in `parent_templates/` to change the layout and functionality.

### Database Models
Update the models in `parent_app.py` to add new fields or relationships.

## Troubleshooting

### Common Issues

1. **Database Connection Error**
   - Check your `DATABASE_URL` in the `.env` file
   - Ensure the database is running and accessible

2. **Port Already in Use**
   - Change the port in `parent_app.py` (line 2853)
   - Default port is 5001

3. **Template Not Found**
   - Ensure all template files are in the `parent_templates/` directory
   - Check file permissions

4. **Import Errors**
   - Make sure all required packages are installed
   - Check Python path and virtual environment

### Logs

The application logs errors to the console when running in debug mode. Check the terminal output for error messages.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the main Student Monitor documentation
3. Check the Flask and SQLAlchemy documentation

## License

This parent portal is part of the Student Monitor system and follows the same licensing terms. 