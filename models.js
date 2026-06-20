const mongoose = require('mongoose');

const DepartmentSchema = new mongoose.Schema({
    id: Number,
    name: String
});

const DoctorSchema = new mongoose.Schema({
    id: Number,
    deptId: Number,
    name: String,
    hours: String
});

const SessionSchema = new mongoose.Schema({
    userId: String,
    step: String,
    bookingData: Object
});

const AppointmentSchema = new mongoose.Schema({
    phone: String,
    appointmentId: String,
    patientName: String,
    department: String,
    doctor: String,
    date: String,
    slot: String,
    issue: String,
    status: { type: String, default: 'PENDING' },
    createdAt: { type: Date, default: Date.now }
});

const Department = mongoose.model('Department', DepartmentSchema);
const Doctor = mongoose.model('Doctor', DoctorSchema);
const Session = mongoose.model('Session', SessionSchema);
const Appointment = mongoose.model('Appointment', AppointmentSchema);

module.exports = { Department, Doctor, Session, Appointment };
