const express = require('express');
const router = express.Router();
const { Session, Department, Doctor, Appointment } = require('./models');
const axios = require('axios');

const MSG91_AUTH_KEY = process.env.MSG91_AUTH_KEY;
const MSG91_INTEGRATED_NUMBER = process.env.MSG91_INTEGRATED_NUMBER;
const MSG91_SEND_URL = "https://api.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/custom/message";

const TIME_SLOTS = ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "04:00 PM", "04:30 PM"];

// Helper to send messages
async function sendWhatsappMessage(toNumber, text, imageUrl = null) {
    const headers = {
        "authkey": MSG91_AUTH_KEY,
        "Content-Type": "application/json"
    };

    let payload = {
        "integrated_number": MSG91_INTEGRATED_NUMBER,
        "content_type": imageUrl ? "media_card" : "text",
        "payload": {
            "to": toNumber,
            "type": imageUrl ? "media_card" : "text",
        }
    };

    if (imageUrl) {
        payload.payload.media_card = {
            "media_url": imageUrl,
            "body_content": text
        };
    } else {
        payload.payload.text = {
            "body": text
        };
    }

    try {
        const response = await axios.post(MSG91_SEND_URL, payload, { headers });
        console.log(`📤 Message sent to ${toNumber}: Status ${response.status}`);
    } catch (error) {
        console.error("🚨 MSG91 Send Failed:", error.response ? error.response.data : error.message);
    }
}

async function processMessage(session, input) {
    const inputLower = input.toLowerCase();

    if (['hi', 'hello', 'start', 'restart', 'menu'].includes(inputLower)) {
        session.step = 'MAIN_MENU';
        session.bookingData = {};
        return {
            text: `👋 Welcome to City Clinic!\nHow can I help you today?\n\n1️⃣ Book Appointment\n2️⃣ View Appointment\n3️⃣ Clinic Information\n4️⃣ Talk to Receptionist\n5️⃣ 🚨 **Emergency**`,
            image: "https://i.ibb.co/vzY8wH2/hospital-welcome.png" // Replace with actual URL
        };
    }

    if (inputLower === 'exit' || inputLower === '0') {
        session.step = 'MAIN_MENU';
        session.bookingData = {};
        return {
            text: `🚫 **Exited.**\n\nHow can I help you?\n\n1️⃣ Book Appointment\n2️⃣ View Appointment\n3️⃣ Clinic Information\n4️⃣ Talk to Receptionist\n5️⃣ 🚨 **Emergency**`,
            image: null
        };
    }

    switch (session.step) {
        case 'MAIN_MENU':
            if (input === '1') {
                session.step = 'SELECT_DEPT';
                const departments = await Department.find().sort({ id: 1 });
                let deptList = `🏥 *Select a Department:*\n(Type 'exit' to go back)\n`;
                departments.forEach((dept, index) => { deptList += `\n${index + 1}️⃣ ${dept.name}`; });
                return { text: deptList, image: "https://i.ibb.co/mSR4G8D/dept-icon.png" };
            } else if (input === '2') {
                session.step = 'VIEW_APPOINTMENT';
                return { text: "📅 Please enter your Appointment ID to view details:", image: null };
            } else if (input === '3') {
                return { text: "📍 *City Clinic Details*\n\n🕒 Open: 9 AM - 9 PM\n🏥 Addr: 123 Health St.\n📞 Tel: 555-0123", image: null };
            } else if (input === '4') {
                return { text: "📞 Our receptionist will be with you shortly. You can also call us directly at 555-0123.", image: null };
            } else if (input === '5') {
                return { text: "🚨 *EMERGENCY ALERT* 🚨\n\nPlease call *108* (Ambulance) immediately.", image: null };
            }
            return { text: "❌ Invalid option. Please type 1, 2, 3, 4 or 5.", image: null };

        case 'START':
            session.step = 'MAIN_MENU';
            return {
                text: `👋 Welcome to City Clinic!\nHow can I help you today?\n\n1️⃣ Book Appointment\n2️⃣ View Appointment\n3️⃣ Clinic Information\n4️⃣ Talk to Receptionist\n5️⃣ 🚨 **Emergency**`,
                image: "https://i.ibb.co/vzY8wH2/hospital-welcome.png"
            };

        case 'VIEW_APPOINTMENT':
            const apt = await Appointment.findOne({ appointmentId: input.toUpperCase() });
            if (apt) {
                return {
                    text: `📅 *Appointment Found*\n\nID: ${apt.appointmentId}\n👤 ${apt.patientName}\n🏥 ${apt.department}\n👨‍⚕️ ${apt.doctor}\n🗓️ ${apt.date} @ ${apt.slot}\n📝 ${apt.issue}`,
                    image: null
                };
            }
            return { text: "❌ Appointment ID not found. Please try again or type 'exit'.", image: null };

        case 'SELECT_DEPT':
            const deptIndex = parseInt(input) - 1;
            const departments = await Department.find().sort({ id: 1 });
            if (departments[deptIndex]) {
                const selectedDept = departments[deptIndex];
                session.bookingData.department = selectedDept.name;
                session.bookingData.deptId = selectedDept.id;
                session.step = 'SELECT_DOCTOR';

                const availableDocs = await Doctor.find({ deptId: selectedDept.id });
                if (availableDocs.length === 0) return { text: "⚠️ No doctors available. Type 'exit'.", image: null };

                let docList = `👨‍⚕️ *Select a Doctor:*\n`;
                availableDocs.forEach((doc, index) => { docList += `\n${index + 1}️⃣ ${doc.name} (${doc.hours})`; });
                return { text: docList, image: "https://i.ibb.co/fD7Hq5x/doctor-icon.png" };
            }
            return { text: "❌ Invalid Department. Try again or type 'exit'.", image: null };

        case 'SELECT_DOCTOR':
            const docIndex = parseInt(input) - 1;
            const availableDocs = await Doctor.find({ deptId: session.bookingData.deptId });
            if (availableDocs[docIndex]) {
                session.bookingData.doctor = availableDocs[docIndex].name;
                session.step = 'SELECT_DATE';
                return { text: "🗓️ *Select a Date:*\n\n1️⃣ Today\n2️⃣ Tomorrow\n3️⃣ Enter Date (DD-MM-YYYY)", image: "https://i.ibb.co/8m0V8Zf/calendar-icon.png" };
            }
            return { text: "❌ Invalid Doctor selection.", image: null };

        case 'SELECT_DATE':
            session.bookingData.date = (input === '1') ? "Today" : (input === '2' ? "Tomorrow" : input);
            session.step = 'SELECT_SLOT';
            let slotList = `⏰ *Select a Time Slot:*\n`;
            TIME_SLOTS.forEach((slot, index) => { slotList += `\n${index + 1}️⃣ ${slot}`; });
            return { text: slotList, image: "https://i.ibb.co/TBPGz1N/clock-icon.png" };

        case 'SELECT_SLOT':
            const slotIdx = parseInt(input) - 1;
            if (TIME_SLOTS[slotIdx]) {
                session.bookingData.slot = TIME_SLOTS[slotIdx];
                session.step = 'ENTER_NAME';
                return { text: "👤 Please enter the *Patient Name*:", image: "https://i.ibb.co/XSBh44m/person-icon.png" };
            }
            return { text: "❌ Invalid Slot.", image: null };

        case 'ENTER_NAME':
            session.bookingData.patientName = input;
            session.step = 'ENTER_ISSUE';
            return { text: "📝 Briefly describe the problem:", image: "https://i.ibb.co/87Mh6Q8/megaphone-icon.png" };

        case 'ENTER_ISSUE':
            session.bookingData.issue = input;
            session.step = 'CONFIRM_BOOKING';
            const bd = session.bookingData;
            return {
                text: `📋 *Confirm Appointment*\n\n👤 ${bd.patientName}\n🏥 ${bd.department}\n👨‍⚕️ ${bd.doctor}\n🗓️ ${bd.date} @ ${bd.slot}\n📝 ${bd.issue}\n\n1️⃣ Confirm\n2️⃣ Cancel`,
                image: "https://i.ibb.co/7C9fX7w/confirmation-icon.png"
            };

        case 'CONFIRM_BOOKING':
            if (input === '1') {
                const appointmentId = 'APT-' + Math.floor(1000 + Math.random() * 9000);
                const newAppointment = new Appointment({ appointmentId, ...session.bookingData });
                await newAppointment.save();

                session.step = 'START';
                session.bookingData = {};
                return { text: `✅ *Booking Confirmed!*\nID: *${appointmentId}*\n\nType 'hi' to start over.`, image: null };
            } else {
                session.step = 'MAIN_MENU';
                session.bookingData = {};
                return { text: "❌ Booking Cancelled. Returning to Main Menu.", image: null };
            }

        default:
            session.step = 'MAIN_MENU';
            return { text: "⚠️ Error. Returning to Main Menu.", image: null };
    }
}

router.post('/msg91', async (req, res) => {
    try {
        const payload = req.body;
        console.log("📩 MSG91 Incoming Payload:", JSON.stringify(payload, null, 2));

        let userNumber = payload.sender || payload.from || payload.customerNumber || (payload.messages && payload.messages[0] && payload.messages[0].from);
        let messageText = "";

        if (payload.text) {
            messageText = payload.text.body || payload.text;
        } else if (payload.messages && payload.messages.length > 0) {
            messageText = payload.messages[0].text.body;
        }

        if (!userNumber || !messageText) {
            return res.json({ status: "ignored", reason: "No number or text" });
        }

        userNumber = userNumber.replace('+', '');

        let session = await Session.findOne({ userId: userNumber });
        if (!session) {
            session = new Session({ userId: userNumber, step: 'START', bookingData: {} });
            await session.save();
        }

        const response = await processMessage(session, messageText.trim());

        await Session.updateOne({ userId: userNumber }, { step: session.step, bookingData: session.bookingData });

        await sendWhatsappMessage(userNumber, response.text, response.image);

        res.json({ status: "ok" });

    } catch (err) {
        console.error("Webhook Error:", err);
        res.status(500).send("Server Error");
    }
});

module.exports = router;
