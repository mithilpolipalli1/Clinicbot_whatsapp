require('dotenv').config();
const mongoose = require('mongoose');
const { Department, Doctor } = require('./models');

mongoose.connect(process.env.MONGO_URI || 'mongodb://127.0.0.1:27017/clinic_bot')
    .then(async () => {
        console.log('✅ Connected to MongoDB');

        // Clear existing data
        await Department.deleteMany({});
        await Doctor.deleteMany({});

        const departments = [
            { id: 1, name: 'General Physician' },
            { id: 2, name: 'Dentist' },
            { id: 3, name: 'Cardiology' },
            { id: 4, name: 'Dermatology' },
            { id: 5, name: 'Pediatrics' }
        ];

        const doctors = [
            { id: 1, deptId: 1, name: 'Dr. Health', hours: '9 AM - 6 PM' },
            { id: 2, deptId: 2, name: 'Dr. Smiley', hours: '10 AM - 2 PM' },
            { id: 3, deptId: 3, name: 'Dr. Heartman', hours: '9 AM - 12 PM' },
            { id: 4, deptId: 3, name: 'Dr. Kapur', hours: '1 PM - 5 PM' },
            { id: 5, deptId: 4, name: 'Dr. Skin', hours: '11 AM - 3 PM' },
            { id: 6, deptId: 5, name: 'Dr. Kiddo', hours: '8 AM - 12 PM' }
        ];

        await Department.insertMany(departments);
        await Doctor.insertMany(doctors);

        console.log('✅ Database Seeded Successfully');
        process.exit();
    })
    .catch(err => {
        console.error('❌ Connection Error:', err);
        process.exit(1);
    });
