import os
import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(".env.local")

def make_outbound_call(to_number: str, twiml_url: str):
    """
    Initiates an outbound call using Twilio with robust error handling.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_CALLER_ID")

    if not all([account_sid, auth_token, from_number]):
        logger.error("❌ Missing Twilio credentials in .env.local")
        raise RuntimeError("Missing Twilio credentials in .env.local")

    try:
        client = Client(account_sid, auth_token)
        
        logger.info(f"🚀 Initiating call to {to_number}...")
        
        call = client.calls.create(
            to=to_number,
            from_=from_number,
            url=twiml_url,
            # Status callback to track call progress (optional but recommended)
            # status_callback="https://your-ngrok-url.dev/status",
            # status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
            # status_callback_method='POST',
        )

        logger.info("✅ Outbound call initiated successfully!")
        logger.info(f"🆔 Call SID: {call.sid}")
        logger.info(f"📊 Status: {call.status}")
        
        return call.sid

    except TwilioRestException as e:
        logger.error(f"❌ Twilio Error: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected Error: {e}")
        return None

if __name__ == "__main__":
    # --- CONFIGURATION ---
    # Replace with the number you want to call
    TARGET_NUMBER = "+918469602264" 
    
    # Replace with your PUBLIC ngrok URL + "/voice"
    TWIML_URL = "https://ethnohistorical-virgen-placably.ngrok-free.dev/voice"
    
    # --- EXECUTE CALL ---
    call_sid = make_outbound_call(TARGET_NUMBER, TWIML_URL)
    
    if call_sid:
        print(f"\nSuccess! Call SID: {call_sid}")
        print("Check your phone or Twilio Console for updates.")
    else:
        print("\nFailed to initiate call. Check logs above.")
