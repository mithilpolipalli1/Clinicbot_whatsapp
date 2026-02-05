// backend/server.js
require('dotenv').config();
const express = require('express');
const bodyParser = require('body-parser');
const mongoose = require('mongoose');
const axios = require('axios');
const { createClient } = require('redis');
const { Department, Doctor, Appointment } = require('./models');

const app = express();
const PORT = process.env.PORT || 3000;

// ------------------------------------------------
// 🔗 DATABASE CONNECTION
// ------------------------------------------------
const MONGO_URI = process.env.MONGO_URI || 'mongodb://127.0.0.1:27017/clinic_bot';

mongoose.connect(MONGO_URI, {
    useNewUrlParser: true,
    useUnifiedTopology: true,
})
    .then(() => console.log(`✅ Connected to MongoDB at ${MONGO_URI}`))
    .catch(err => {
        console.error('❌ MongoDB Connection Error:', err.message);
    });

// ------------------------------------------------
// 🧠 REDIS SESSION MANAGER
// ------------------------------------------------
const redisClient = createClient({
    url: `redis://${process.env.REDIS_HOST || 'zasya_redis'}:6379`
});

redisClient.on('error', (err) => console.error('🔴 Clinic: Redis Connection Error', err));

(async () => {
    try {
        await redisClient.connect();
        console.log("✅ Clinic: Connected to Redis");
    } catch (err) {
        console.error("❌ Clinic: Redis Connection Failed. Bot will continue but sessions may fail.", err.message);
    }
})();

class SessionManager {
    static async get(phone) {
        try {
            if (!redisClient.isOpen) return { step: 'START', bookingData: {} };
            const data = await redisClient.get(`session:clinic:${phone}`);
            return data ? JSON.parse(data) : { step: 'START', bookingData: {} };
        } catch (e) {
            return { step: 'START', bookingData: {} };
        }
    }
    static async save(phone, session) {
        try {
            if (redisClient.isOpen) {
                await redisClient.set(`session:clinic:${phone}`, JSON.stringify(session), { EX: 3600 });
            }
        } catch (e) {
            console.error("❌ Clinic: Failed to save session", e.message);
        }
    }
}

app.use(bodyParser.json());

// ------------------------------------------------
// 📤 SEND MESSAGE FUNCTION
// ------------------------------------------------

const TIME_SLOTS = ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "04:00 PM", "04:30 PM"];

// ------------------------------------------------
// 📤 SEND MESSAGE FUNCTION
// ------------------------------------------------
async function sendWhatsappMessage(toNumber, text, imageUrl = null) {
    const headers = {
        "authkey": process.env.MSG91_AUTH_KEY,
        "Content-Type": "application/json"
    };

    let payload = {
        "integrated_number": process.env.MSG91_INTEGRATED_NUMBER,
        "content_type": imageUrl ? "media_card" : "text",
        "payload": {
            "to": toNumber,
            "type": imageUrl ? "media_card" : "text",
        }
    };

    if (imageUrl) {
        payload.payload.media_card = { "media_url": imageUrl, "body_content": text };
    } else {
        payload.payload.text = { "body": text };
    }

    try {
        await axios.post("https://api.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/custom/message", payload, { headers });
        console.log(`📤 Message sent to ${toNumber}`);
    } catch (error) {
        console.error("🚨 MSG91 Error:", error.response ? error.response.data : error.message);
    }
}

// ------------------------------------------------
// 🧠 CLINIC BOT LOGIC ENGINE
// ------------------------------------------------
async function processMessage(session, input, phone) {
    const inputLower = input.toLowerCase();

    if (['hi', 'hello', 'start', 'restart', 'menu'].includes(inputLower)) {
        session.step = 'MAIN_MENU';
        session.bookingData = {};
        return {
            text: `Welcome to City Clinic!\nHow can I help you today?\n\n1️⃣ Book Appointment\n2️⃣ View Appointment\n3️⃣ Clinic Information\n4️⃣ Talk to Receptionist\n5️⃣ Emergency\n\n👉 *Type the number to select.*`,
            image: "https://i.ibb.co/vzY8wH2/hospital-welcome.png"
        };
    }

    if (inputLower === 'exit' || input === '0') {
        session.step = 'MAIN_MENU'; session.bookingData = {};
        return { text: "🚫 *Exited to Main Menu.*\n\n1️⃣ Book Appointment\n2️⃣ View Appointment\n3️⃣ Clinic Information\n4️⃣ Talk to Receptionist\n5️⃣ Emergency\n\n👉 *Type the number to select.*", image: null };
    }

    switch (session.step) {
        case 'MAIN_MENU':
            if (input === '1') {
                session.step = 'SELECT_DEPT';
                const deptsList = await Department.find().sort({ id: 1 });

                if (deptsList.length === 0) {
                    console.log("⚠️ Clinic: No departments found in DB");
                    return { text: "🏥 *Select a Department:*\n\n⚠️ No departments available at the moment. Please contact support or try again later.", image: "https://i.ibb.co/mSR4G8D/dept-icon.png" };
                }

                let listOutput = `🏥 *Select a Department:*\n`;
                deptsList.forEach((d, i) => listOutput += `\n${i + 1}️⃣ ${d.name}`);
                listOutput += `\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*`;
                return { text: listOutput, image: "https://i.ibb.co/mSR4G8D/dept-icon.png" };
            } else if (input === '2') {
                const appointments = await Appointment.find({ phone: phone }).sort({ createdAt: -1 });
                if (appointments.length === 0) {
                    return { text: "❌ No appointments found for your number.\n\nType *1* to book a new appointment.", image: null };
                }

                let response = "� *Your Appointments:*\n";
                // Show last 3 appointments to keep message clean
                appointments.slice(0, 3).forEach((apt) => {
                    response += `\n━━━━━━━━━━━━━━\n🆔 *${apt.appointmentId}*\n👤 Name: ${apt.patientName}\n👨‍⚕️ Dr: ${apt.doctor}\n🗓️ ${apt.date} @ ${apt.slot}\n📝 Issue: ${apt.issue}`;
                });
                response += "\n\nType 'hi' to return to main menu.";
                return { text: response, image: null };
            } else if (input === '3') {
                return { text: "📍 *City Clinic Details*\n\n🕒 Open: 9 AM - 9 PM\n🏥 Addr: 123 Health St.\n📞 Tel: 555-0123", image: null };
            } else if (input === '4') {
                return { text: "📞 Our receptionist will be with you shortly. You can also call us directly at 555-0123.", image: null };
            } else if (input === '5') {
                return { text: "🚨 *EMERGENCY ALERT* 🚨\n\nPlease call *108* (Ambulance) immediately.", image: null };
            }
            return { text: "❌ Invalid option. Please type 1, 2, 3, 4 or 5.", image: null };

        case 'SELECT_DEPT':
            const deptsFetch = await Department.find().sort({ id: 1 });
            const selectedDept = deptsFetch[parseInt(input) - 1];
            if (selectedDept) {
                session.bookingData.department = selectedDept.name;
                session.bookingData.deptId = selectedDept.id;
                session.step = 'SELECT_DOC';
                const docsFetch = await Doctor.find({ deptId: selectedDept.id });
                if (docsFetch.length === 0) {
                    return { text: `⚠️ No doctors available in *${selectedDept.name}*. Type 'exit' to go back.`, image: null };
                }
                let docListString = `Department selected: *${selectedDept.name}*\n\n👨‍⚕️ *Select a Doctor:*\n`;
                docsFetch.forEach((d, i) => docListString += `\n${i + 1}️⃣ ${d.name} (${d.hours})`);
                docListString += `\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*`;
                return { text: docListString, image: "https://i.ibb.co/fD7Hq5x/doctor-icon.png" };
            }
            return { text: "❌ Invalid Department. Please select a number from the list.", image: null };

        case 'SELECT_DOC':
            const docsInDept = await Doctor.find({ deptId: session.bookingData.deptId });
            const docChosen = docsInDept[parseInt(input) - 1];
            if (docChosen) {
                session.bookingData.doctor = docChosen.name;
                session.step = 'SELECT_DATE';
                return {
                    text: `Doctor selected: *${docChosen.name}*\n\n🗓️ *Select a Date:*\n\n1️⃣ Today\n2️⃣ Tomorrow\n3️⃣ Enter Date\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*`,
                    image: "https://i.ibb.co/8m0V8Zf/calendar-icon.png"
                };
            }
            return { text: "❌ Invalid Doctor selection.", image: null };

        case 'SELECT_DATE':
            const dateLabel = (input === '1') ? "Today" : (input === '2' ? "Tomorrow" : input);
            session.bookingData.date = dateLabel;
            session.step = 'SELECT_SLOT';
            let slotPicker = `Date selected: *${dateLabel}*\n\n⏰ *Select a Time Slot:*\n`;
            TIME_SLOTS.forEach((sl, i) => slotPicker += `\n${i + 1}️⃣ ${sl}`);
            slotPicker += `\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*`;
            return { text: slotPicker, image: "https://i.ibb.co/TBPGz1N/clock-icon.png" };

        case 'SELECT_SLOT':
            const slotSelected = TIME_SLOTS[parseInt(input) - 1];
            if (slotSelected) {
                session.bookingData.slot = slotSelected;
                session.step = 'ENTER_NAME';
                return {
                    text: `Time slot selected: *${slotSelected}*\n\n👤 Please enter the *Patient Name*:\n(Type 0 to go back)`,
                    image: "https://i.ibb.co/XSBh44m/person-icon.png"
                };
            }
            return { text: "❌ Invalid Slot.", image: null };

        case 'ENTER_NAME':
            session.bookingData.patientName = input;
            session.step = 'ENTER_ISSUE';
            return {
                text: `📝 Briefly describe the problem:\n(Type 0 to go back)`,
                image: "https://i.ibb.co/87Mh6Q8/megaphone-icon.png"
            };

        case 'ENTER_ISSUE':
            session.bookingData.issue = input;
            session.step = 'CONFIRM_BOOKING';
            const data = session.bookingData;
            return {
                text: `📋 *Confirm Appointment*\n\n👤 ${data.patientName}\n🏥 ${data.department}\n👨‍⚕️ ${data.doctor}\n🗓️ ${data.date} @ ${data.slot}\n📝 ${data.issue}\n\n1️⃣ Confirm\n2️⃣ Cancel\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*`,
                image: "https://i.ibb.co/7C9fX7w/confirmation-icon.png"
            };

        case 'CONFIRM_BOOKING':
            if (input === '1') {
                const aptId = 'APT-' + Math.floor(1000 + Math.random() * 8999);
                await new Appointment({
                    phone: phone,
                    appointmentId: aptId,
                    ...session.bookingData
                }).save();
                session.step = 'START';
                return { text: `✅ *Confirmed!*\nID: *${aptId}*\n\nYour appointment is booked. You can view it anytime by selecting 'View Appointment' from the menu.\n\nType 'hi' to start over.`, image: null };
            }
            session.step = 'MAIN_MENU';
            return { text: "❌ Cancelled. Returning to Main Menu.", image: null };

        default:
            session.step = 'MAIN_MENU';
            return { text: "⚠️ Error. Type 'hi' to restart.", image: null };
    }
}

// ------------------------------------------------
// 📩 MSG91 WEBHOOK
// ------------------------------------------------
app.post('/webhook/msg91', async (req, res) => {
    try {
        const payload = req.body;
        console.log("📩 Clinic Webhook Received:", JSON.stringify(payload));

        let userNum = payload.phone || payload.customerNumber || payload.sender || payload.from || (payload.messages && payload.messages[0].from);
        let msgText = payload.text || payload.content || (payload.text && payload.text.body) || (payload.messages && payload.messages[0].text.body);

        if (!userNum || !msgText) {
            console.log("⚠️ Clinic: Incomplete data. userNum:", userNum, "msgText:", msgText);
            return res.json({ status: "ignored" });
        }

        userNum = userNum.toString().replace(/\+/g, "");
        console.log(`👤 Clinic: Identified User: ${userNum} | Text: ${msgText}`);

        // 1. Get Session with fallback
        let session;
        try {
            session = await SessionManager.get(userNum);
            console.log(`🔄 Clinic: Current Step: ${session.step}`);
        } catch (e) {
            console.error("❌ Clinic: Redis Get Error", e.message);
            session = { step: 'START', bookingData: {} };
        }

        // 2. Process Message
        let responseMsg;
        try {
            responseMsg = await processMessage(session, msgText.trim(), userNum);
            console.log(`📤 Clinic: Generated Response`);
        } catch (e) {
            console.error("❌ Clinic: processMessage Error", e.message);
            responseMsg = { text: "⚠️ Clinic service is temporarily slow. Please try again.", image: null };
        }

        // 3. Save Session
        try {
            await SessionManager.save(userNum, session);
        } catch (e) {
            console.error("❌ Clinic: Redis Save Error", e.message);
        }

        // 4. Respond to Router
        if (req.body.isRouter || req.body.phone) {
            console.log("✅ Clinic: Returning JSON to Router");
            return res.json({ text: responseMsg.text, image: responseMsg.image });
        }

        // 5. Fallback for direct MSG91
        await sendWhatsappMessage(userNum, responseMsg.text, responseMsg.image);
        res.json({ status: "ok" });
    } catch (err) {
        console.error("🚨 Clinic: Webhook Critical Error:", err);
        res.status(500).json({ error: "Internal Server Error" });
    }
});

app.listen(PORT, () => {
    console.log(`🚀 Clinic Bot Server running on port ${PORT}`);
});