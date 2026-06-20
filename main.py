"""
=================================================================================================
🏥 CLINIC BOT - ENTERPRISE SERVER (Python/FastAPI Edition)
=================================================================================================
Migrated from Node.js server.js → Python main.py
Preserves all API contracts, state machine, MongoDB operations, and response shapes.
=================================================================================================
"""

import os
import re
import sys
import json
import uuid
import random
import logging
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import quote

import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("clinic")

PORT = int(os.getenv("PORT", "3000"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/clinic_bot")
REDIS_HOST = os.getenv("REDIS_HOST", "zasya_redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
UPI_ID = os.getenv("UPI_ID", "")
MERCHANT_NAME = os.getenv("MERCHANT_NAME", "Mithil Polipalli")

# ---------------------------------------------------------------------------
# GLOBALS (initialised in lifespan)
# ---------------------------------------------------------------------------
mongo_client: Optional[AsyncIOMotorClient] = None
db = None  # MongoDB database reference
redis_client: Optional[aioredis.Redis] = None

# ---------------------------------------------------------------------------
# TIME SLOTS (hardcoded)
# ---------------------------------------------------------------------------
TIME_SLOTS = ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "04:00 PM", "04:30 PM"]

# ---------------------------------------------------------------------------
# PHONE NORMALIZATION
# ---------------------------------------------------------------------------
def normalize_phone(phone: str) -> str:
    """Strip '+' prefix and any non-digit chars from phone number."""
    if not phone:
        return ""
    clean = re.sub(r"\D", "", str(phone))
    return clean

# ---------------------------------------------------------------------------
# SESSION MANAGER (Redis)
# ---------------------------------------------------------------------------
class SessionManager:
    @staticmethod
    async def get(phone: str) -> dict:
        try:
            if redis_client is None:
                return {"step": "START", "bookingData": {}}
            data = await redis_client.get(f"session:clinic:{phone}")
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"Redis GET error for clinic:{phone}: {e}")
        return {"step": "START", "bookingData": {}}

    @staticmethod
    async def save(phone: str, session: dict) -> None:
        try:
            if redis_client is not None:
                await redis_client.set(
                    f"session:clinic:{phone}", json.dumps(session), ex=3600
                )
        except Exception as e:
            logger.error(f"❌ Clinic: Failed to save session: {e}")


# ---------------------------------------------------------------------------
# CLINIC BOT LOGIC ENGINE
# ---------------------------------------------------------------------------
def get_welcome_response(session: dict) -> dict:
    session["step"] = "MAIN_MENU"
    session["bookingData"] = {}
    return {
        "text": (
            "Welcome to City Clinic!\n"
            "How can I help you today?\n\n"
            "1️⃣ Book Appointment\n"
            "2️⃣ View Appointment\n"
            "3️⃣ Clinic Information\n"
            "4️⃣ Talk to Receptionist\n"
            "5️⃣ Emergency\n\n"
            "👉 *Type the number to select.*"
        ),
        "image": "https://i.ibb.co/vzY8wH2/hospital-welcome.png",
    }


async def process_message(session: dict, inp: str, phone: str) -> dict:
    """Main state machine for clinic bot conversations."""
    input_lower = inp.lower()

    # Global reset triggers
    if input_lower in ("hi", "hello", "start", "restart", "menu"):
        return get_welcome_response(session)

    # Exit trigger
    if input_lower == "exit":
        session["step"] = "MAIN_MENU"
        session["bookingData"] = {}
        return {
            "text": (
                "🚫 *Exited to Main Menu.*\n\n"
                "1️⃣ Book Appointment\n"
                "2️⃣ View Appointment\n"
                "3️⃣ Clinic Information\n"
                "4️⃣ Talk to Receptionist\n"
                "5️⃣ Emergency\n\n"
                "👉 *Type the number to select.*"
            ),
            "image": None,
        }

    step = session.get("step", "START")

    # ── MAIN MENU ──
    if step == "MAIN_MENU":
        if inp == "1":
            session["step"] = "SELECT_DEPT"
            session["bookingData"] = {}  # Clear bookingData when starting new booking
            try:
                depts_cursor = db.departments.find().sort("id", 1)
                depts_list = await depts_cursor.to_list(length=100)
            except Exception as e:
                logger.error(f"MongoDB departments fetch error: {e}")
                depts_list = []

            if not depts_list:
                logger.warning("⚠️ Clinic: No departments found in DB")
                return {
                    "text": "🏥 *Select a Department:*\n\n⚠️ No departments available at the moment. Please contact support or try again later.",
                    "image": "https://i.ibb.co/mSR4G8D/dept-icon.png",
                }

            list_output = "🏥 *Select a Department:*\n"
            for i, d in enumerate(depts_list):
                list_output += f"\n{i + 1}️⃣ {d['name']}"
            list_output += "\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*"
            return {"text": list_output, "image": "https://i.ibb.co/mSR4G8D/dept-icon.png"}

        elif inp == "2":
            # Delete ALL past appointments
            today_str = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date().isoformat()
            try:
                await db.appointments.delete_many({"date": {"$lt": today_str}})
                appointments = await db.appointments.find({
                    "phone": phone,
                    "status": "CONFIRMED",
                    "date": {"$gte": today_str},
                }).sort([("date", 1), ("slot", 1)]).to_list(length=100)
            except Exception as e:
                logger.error(f"MongoDB appointments fetch error: {e}")
                appointments = []

            if not appointments:
                return {"text": "❌ No upcoming appointments found.\n\nType *1* to book a new appointment.", "image": None}

            response = "🩺 *Active Appointments:*\n"
            for apt in appointments:
                response += (
                    f"\n━━━━━━━━━━━━━━\n"
                    f"🆔 *{apt.get('appointmentId', 'N/A')}*\n"
                    f"👤 Name: {apt.get('patientName', 'N/A')}\n"
                    f"👨‍⚕️ Dr: {apt.get('doctor', 'N/A')}\n"
                    f"🗓️ {apt.get('date', '')} @ {apt.get('slot', '')}\n"
                    f"📝 Issue: {apt.get('issue', 'N/A')}"
                )
            response += "\n\nType 'hi' to return to main menu."
            return {"text": response, "image": None}

        elif inp == "3":
            return {
                "text": "📍 *City Clinic Details*\n\n🕒 Open: 9 AM - 9 PM\n🏥 Addr: 123 Health St.\n📞 Tel: 555-0123",
                "image": None,
            }

        elif inp == "4":
            return {
                "text": "📞 Our receptionist will be with you shortly. You can also call us directly at 555-0123.",
                "image": None,
            }

        elif inp == "5":
            return {
                "text": "🚨 *EMERGENCY ALERT* 🚨\n\nPlease call *108* (Ambulance) immediately.",
                "image": None,
            }

        return {"text": "❌ Invalid option. Please type 1, 2, 3, 4 or 5.", "image": None}

    # ── SELECT DEPARTMENT ──
    elif step == "SELECT_DEPT":
        if inp == "0":
            return get_welcome_response(session)
        try:
            depts_fetch = await db.departments.find().sort("id", 1).to_list(length=100)
            idx = int(inp) - 1
            if 0 <= idx < len(depts_fetch):
                selected_dept = depts_fetch[idx]
                session["bookingData"]["department"] = selected_dept["name"]
                session["bookingData"]["deptId"] = selected_dept["id"]
                session["step"] = "SELECT_DOC"

                docs_fetch = await db.doctors.find({"deptId": selected_dept["id"]}).to_list(length=100)
                if not docs_fetch:
                    return {"text": f"⚠️ No doctors available in *{selected_dept['name']}*. Type 'exit' to go back.", "image": None}

                doc_list = f"Department selected: *{selected_dept['name']}*\n\n👨‍⚕️ *Select a Doctor:*\n"
                for i, d in enumerate(docs_fetch):
                    doc_list += f"\n{i + 1}️⃣ {d['name']} ({d.get('hours', '')})"
                doc_list += "\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*"
                return {"text": doc_list, "image": "https://i.ibb.co/fD7Hq5x/doctor-icon.png"}
            else:
                return {"text": "❌ Invalid Department. Please select a number from the list.", "image": None}
        except (ValueError, IndexError):
            return {"text": "❌ Invalid Department. Please select a number from the list.", "image": None}
        except Exception as e:
            logger.error(f"SELECT_DEPT error: {e}")
            return {"text": "⚠️ Error fetching departments. Please try again.", "image": None}

    # ── SELECT DOCTOR ──
    elif step == "SELECT_DOC":
        if inp == "0":
            return get_welcome_response(session)
        try:
            dept_id = session.get("bookingData", {}).get("deptId")
            docs_in_dept = await db.doctors.find({"deptId": dept_id}).to_list(length=100)
            idx = int(inp) - 1
            if 0 <= idx < len(docs_in_dept):
                doc_chosen = docs_in_dept[idx]
                session["bookingData"]["doctor"] = doc_chosen["name"]
                session["bookingData"]["doctorHours"] = doc_chosen.get("hours", "")
                session["step"] = "SELECT_DATE"

                # Determine if today is still bookable based on doctor's end hour or 2 PM rule
                today_available = True
                
                # Check 2 PM rule (IST timezone: UTC + 5:30)
                ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                now_hour = ist_now.hour
                
                if now_hour >= 14:
                    today_available = False
                else:
                    doc_hours = doc_chosen.get("hours", "")
                    if doc_hours:
                        try:
                            # Parse end time from format like '10 AM - 2 PM' or '9 AM - 6 PM'
                            end_part = doc_hours.split("-")[-1].strip()  # e.g. '2 PM' or '6 PM'
                            end_hour_str, end_ampm = end_part.split()
                            end_hour = int(end_hour_str)
                            if end_ampm.upper() == "PM" and end_hour != 12:
                                end_hour += 12
                            elif end_ampm.upper() == "AM" and end_hour == 12:
                                end_hour = 0
                            if now_hour >= end_hour:
                                today_available = False
                        except Exception:
                            pass  # If parsing fails, keep today available

                if today_available:
                    date_menu = "1️⃣ Today\n2️⃣ Tomorrow\n3️⃣ Enter Date"
                else:
                    date_menu = "1️⃣ Tomorrow\n2️⃣ Enter Date"
                    session["bookingData"]["todayUnavailable"] = True

                return {
                    "text": (
                        f"Doctor selected: *{doc_chosen['name']}*\n\n"
                        "🗓️ *Select a Date:*\n\n"
                        f"{date_menu}\n"
                        "0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*"
                    ),
                    "image": "https://i.ibb.co/8m0V8Zf/calendar-icon.png",
                }
            return {"text": "❌ Invalid Doctor selection.", "image": None}
        except (ValueError, IndexError):
            return {"text": "❌ Invalid Doctor selection.", "image": None}
        except Exception as e:
            logger.error(f"SELECT_DOC error: {e}")
            return {"text": "⚠️ Error fetching doctors. Please try again.", "image": None}

    # ── SELECT DATE ──
    elif step == "SELECT_DATE":
        if inp == "0":
            return get_welcome_response(session)
        
        ist_date = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
        today_unavailable = session.get("bookingData", {}).get("todayUnavailable", False)
        final_date = inp
        if today_unavailable:
            # Options shifted: 1=Tomorrow, 2=Enter Date
            if inp == "1":
                final_date = (ist_date + timedelta(days=1)).isoformat()
            elif inp == "2":
                # User will type a custom date next — prompt them
                session["step"] = "ENTER_CUSTOM_DATE"
                return {"text": "📅 Please enter the date in *YYYY-MM-DD* format:\n(e.g. 2026-06-25)\n(Type 0 to go back)", "image": None}
            else:
                return {"text": "❌ Invalid Date selection.", "image": None}
        else:
            if inp == "1":
                final_date = ist_date.isoformat()
            elif inp == "2":
                final_date = (ist_date + timedelta(days=1)).isoformat()
            elif inp == "3":
                session["step"] = "ENTER_CUSTOM_DATE"
                return {"text": "📅 Please enter the date in *YYYY-MM-DD* format:\n(e.g. 2026-06-25)\n(Type 0 to go back)", "image": None}
            else:
                return {"text": "❌ Invalid Date selection.", "image": None}

        session["bookingData"]["date"] = final_date
        session["step"] = "SELECT_SLOT"
        slot_picker = f"Date selected: *{final_date}*\n\n⏰ *Select a Time Slot:*\n"
        for i, sl in enumerate(TIME_SLOTS):
            slot_picker += f"\n{i + 1}️⃣ {sl}"
        slot_picker += "\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*"
        return {"text": slot_picker, "image": "https://i.ibb.co/TBPGz1N/clock-icon.png"}

    # ── ENTER CUSTOM DATE ──
    elif step == "ENTER_CUSTOM_DATE":
        if inp == "0":
            session["step"] = "SELECT_DATE"
            today_available = not session.get("bookingData", {}).get("todayUnavailable", False)
            if today_available:
                date_menu = "1️⃣ Today\n2️⃣ Tomorrow\n3️⃣ Enter Date"
            else:
                date_menu = "1️⃣ Tomorrow\n2️⃣ Enter Date"
            return {
                "text": (
                    f"Doctor selected: *{session.get('bookingData', {}).get('doctor')}*\n\n"
                    "🗓️ *Select a Date:*\n\n"
                    f"{date_menu}\n"
                    "0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*"
                ),
                "image": "https://i.ibb.co/8m0V8Zf/calendar-icon.png",
            }
        try:
            # Validate date format
            parsed = datetime.strptime(inp.strip(), "%Y-%m-%d").date()
            ist_date = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
            if parsed < ist_date:
                return {"text": "❌ Please enter a future date (YYYY-MM-DD):\n(Type 0 to go back)", "image": None}
            session["bookingData"]["date"] = parsed.isoformat()
            session["step"] = "SELECT_SLOT"
            slot_picker = f"Date selected: *{parsed.isoformat()}*\n\n⏰ *Select a Time Slot:*\n"
            for i, sl in enumerate(TIME_SLOTS):
                slot_picker += f"\n{i + 1}️⃣ {sl}"
            slot_picker += "\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*"
            return {"text": slot_picker, "image": "https://i.ibb.co/TBPGz1N/clock-icon.png"}
        except ValueError:
            return {"text": "❌ Invalid format. Please enter date as *YYYY-MM-DD*:\n(e.g. 2026-06-25)\n(Type 0 to go back)", "image": None}

    # ── SELECT SLOT ──
    elif step == "SELECT_SLOT":
        if inp == "0":
            return get_welcome_response(session)
        try:
            idx = int(inp) - 1
            if 0 <= idx < len(TIME_SLOTS):
                slot_selected = TIME_SLOTS[idx]
                session["bookingData"]["slot"] = slot_selected
                session["step"] = "ENTER_NAME"
                return {
                    "text": f"Time slot selected: *{slot_selected}*\n\n👤 Please enter the *Patient Name*:\n(Type 0 to go back)",
                    "image": "https://i.ibb.co/XSBh44m/person-icon.png",
                }
            return {"text": "❌ Invalid Slot. Please select a slot number or 0 to go back.", "image": None}
        except ValueError:
            return {"text": "❌ Invalid Slot. Please select a slot number or 0 to go back.", "image": None}

    # ── ENTER NAME ──
    elif step == "ENTER_NAME":
        if inp == "0":
            session["step"] = "SELECT_SLOT"
            final_date = session.get("bookingData", {}).get("date", "")
            slot_picker = f"Date selected: *{final_date}*\n\n⏰ *Select a Time Slot:*\n"
            for i, sl in enumerate(TIME_SLOTS):
                slot_picker += f"\n{i + 1}️⃣ {sl}"
            slot_picker += "\n0️⃣ Back to Main Menu\n\n👉 *Type the number to select.*"
            return {"text": slot_picker, "image": "https://i.ibb.co/TBPGz1N/clock-icon.png"}
        session["bookingData"]["patientName"] = inp
        session["step"] = "ENTER_ISSUE"
        return {
            "text": "📝 Briefly describe the problem:\n(Type 0 to go back)",
            "image": "https://i.ibb.co/87Mh6Q8/megaphone-icon.png",
        }

    # ── ENTER ISSUE ──
    elif step == "ENTER_ISSUE":
        if inp == "0":
            session["step"] = "ENTER_NAME"
            slot_selected = session.get("bookingData", {}).get("slot", "")
            return {
                "text": f"Time slot selected: *{slot_selected}*\n\n👤 Please enter the *Patient Name*:\n(Type 0 to go back)",
                "image": "https://i.ibb.co/XSBh44m/person-icon.png",
            }
        session["bookingData"]["issue"] = inp
        session["step"] = "CONFIRM_BOOKING"
        bd = session["bookingData"]
        return {
            "text": (
                f"📋 *Confirm Appointment*\n\n"
                f"👤 {bd.get('patientName', '')}\n"
                f"🏥 {bd.get('department', '')}\n"
                f"👨‍⚕️ {bd.get('doctor', '')}\n"
                f"🗓️ {bd.get('date', '')} @ {bd.get('slot', '')}\n"
                f"📝 {bd.get('issue', '')}\n\n"
                "1️⃣ Confirm\n2️⃣ Cancel\n0️⃣ Back to Main Menu\n\n"
                "👉 *Type the number to select.*"
            ),
            "image": "https://i.ibb.co/7C9fX7w/confirmation-icon.png",
        }

    # ── CONFIRM BOOKING ──
    elif step == "CONFIRM_BOOKING":
        if inp == "0":
            return get_welcome_response(session)
        if inp == "1":
            amount = 200  # Consultation Fee
            apt_id = f"APT-{uuid.uuid4().hex[:6].upper()}"

            try:
                await db.appointments.insert_one({
                    "phone": phone,
                    "appointmentId": apt_id,
                    "status": "PENDING",
                    "patientName": session["bookingData"].get("patientName", ""),
                    "department": session["bookingData"].get("department", ""),
                    "doctor": session["bookingData"].get("doctor", ""),
                    "date": session["bookingData"].get("date", ""),
                    "slot": session["bookingData"].get("slot", ""),
                    "issue": session["bookingData"].get("issue", ""),
                    "createdAt": datetime.utcnow(),
                })
            except Exception as e:
                logger.error(f"MongoDB appointment insert error: {e}")
                return {"text": "⚠️ Error saving appointment. Please try again.", "image": None}

            pay_link = f"http://18.61.156.35/pay?am={amount}"
            merchant_enc = quote(MERCHANT_NAME)
            upi_data = f"upi://pay?pa={UPI_ID}&pn={merchant_enc}&am={amount}&cu=INR"
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(upi_data)}"

            session["step"] = "CONFIRM_PAYMENT"
            return {
                "text": (
                    f"💳 *Consultation Fee Required*\n\n"
                    f"To confirm your appointment, please pay the consultation fee of *₹{amount}*.\n\n"
                    f"👉 *Click to Pay:* {pay_link}\n\n"
                    "Scan the QR code below and type *1* or *Paid* once done."
                ),
                "image": qr_url,
            }

        session["step"] = "MAIN_MENU"
        session["bookingData"] = {}
        return {"text": "❌ Cancelled. Returning to Main Menu.", "image": None}

    # ── CONFIRM PAYMENT ──
    elif step == "CONFIRM_PAYMENT":
        is_paid = (inp == "1") or ("paid" in inp.lower())
        if is_paid:
            try:
                last_apt = await db.appointments.find_one_and_update(
                    {"phone": phone, "status": "PENDING"},
                    {"$set": {"status": "CONFIRMED"}},
                    sort=[("createdAt", -1)],
                )
                apt_id_display = last_apt.get("appointmentId", "Unknown") if last_apt else "Unknown"
            except Exception as e:
                logger.error(f"MongoDB payment confirmation error: {e}")
                apt_id_display = "Unknown"

            session["step"] = "START"
            session["bookingData"] = {}  # Clear bookingData on completion
            return {
                "text": (
                    f"✅ *Confirmed & Paid!*\n"
                    f"ID: *{apt_id_display}*\n\n"
                    "Thank you for the payment. Your appointment is successfully booked.\n\n"
                    "Type 'hi' to start over."
                ),
                "image": None,
            }

        session["step"] = "MAIN_MENU"
        session["bookingData"] = {}  # Clear bookingData on payment failure/cancel
        return {"text": "🚫 Payment not verified. Returning to menu.", "image": None}

    # ── DEFAULT ──
    else:
        session["step"] = "MAIN_MENU"
        return {"text": "⚠️ Error. Type 'hi' to restart.", "image": None}


# ---------------------------------------------------------------------------
# FASTAPI LIFESPAN
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(application: FastAPI):
    global mongo_client, db, redis_client

    # ── Startup ──
    logger.info("🏥 Clinic Bot starting up...")

    # Redis
    redis_client = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, decode_responses=True
    )
    try:
        await redis_client.ping()
        logger.info("✅ Clinic: Connected to Redis")
    except Exception as e:
        logger.error(f"❌ Clinic: Redis Connection Failed. Bot will continue but sessions may fail. {e}")

    # MongoDB
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client["clinic_bot"]
        # Verify connection
        await mongo_client.admin.command("ping")
        logger.info(f"✅ Connected to MongoDB at {MONGO_URI}")
    except Exception as e:
        logger.error(f"❌ MongoDB Connection Error: {e}")

    logger.info(f"🚀 Clinic Bot Server running on port {PORT}")

    yield

    # ── Shutdown ──
    logger.info("Graceful shutdown starting...")
    if mongo_client:
        mongo_client.close()
    if redis_client:
        await redis_client.close()
    logger.info("Graceful shutdown complete")


app = FastAPI(lifespan=lifespan, title="Clinic Bot API")


# ---------------------------------------------------------------------------
# PYDANTIC MODELS
# ---------------------------------------------------------------------------
class WebhookRequest(BaseModel):
    phone: Optional[str] = None
    customerNumber: Optional[str] = None
    sender: Optional[str] = None
    from_field: Optional[str] = None
    text: Optional[str] = None
    content: Optional[str] = None
    messages: Optional[list] = None

    class Config:
        # Allow 'from' field (reserved keyword in Python)
        populate_by_name = True


# ---------------------------------------------------------------------------
# ENDPOINTS
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "clinic-bot"}


@app.post("/webhook/msg91")
async def webhook_msg91(request: Request):
    try:
        payload = await request.json()
        logger.info(f"📩 Clinic Webhook Received: {json.dumps(payload, default=str)}")

        # Extract phone number (try multiple field names)
        user_num = (
            payload.get("phone")
            or payload.get("customerNumber")
            or payload.get("sender")
            or payload.get("from")
        )
        if not user_num and payload.get("messages"):
            try:
                user_num = payload["messages"][0].get("from")
            except (IndexError, KeyError, TypeError):
                pass

        # Extract message text
        msg_text = payload.get("text") or payload.get("content")
        if not msg_text and payload.get("messages"):
            try:
                msg_text = payload["messages"][0]["text"]["body"]
            except (IndexError, KeyError, TypeError):
                pass

        if not user_num or not msg_text:
            logger.warning(f"⚠️ Clinic: Incomplete data. userNum: {user_num}, msgText: {msg_text}")
            return {"status": "ignored"}

        user_num = normalize_phone(str(user_num))
        logger.info(f"👤 Clinic: Identified User: {user_num} | Text: {msg_text}")

        # 1. Get Session with fallback
        try:
            session = await SessionManager.get(user_num)
            logger.info(f"🔄 Clinic: Current Step: {session.get('step')}")
        except Exception as e:
            logger.error(f"❌ Clinic: Redis Get Error: {e}")
            session = {"step": "START", "bookingData": {}}

        # 2. Process Message
        try:
            response_msg = await process_message(session, msg_text.strip(), user_num)
            logger.info("📤 Clinic: Generated Response")
        except Exception as e:
            logger.error(f"❌ Clinic: processMessage Error: {e}")
            response_msg = {"text": "⚠️ Clinic service is temporarily slow. Please try again.", "image": None}

        # 3. Save Session
        try:
            await SessionManager.save(user_num, session)
        except Exception as e:
            logger.error(f"❌ Clinic: Redis Save Error: {e}")

        # 4. Respond to Router (always return JSON)
        logger.info("✅ Clinic: Returning JSON to Router")
        return {"text": response_msg.get("text", ""), "image": response_msg.get("image")}

    except Exception as err:
        logger.error(f"🚨 Clinic: Webhook Critical Error: {err}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Internal Server Error"})


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, workers=2)
