#!/usr/bin/env python3
"""
VT/ME Multistep Call Campaign - Bland.ai
3-step sequence:
  Step 1: Initial call (Sarah introduces Vega Estimating AI)
  Step 2: Follow-up call 3 days later (if no answer / voicemail on step 1)
  Step 3: Final call 7 days later (last attempt)

Usage:
  python3 vt_me_bland_campaign.py --step 1        # Launch step 1 calls
  python3 vt_me_bland_campaign.py --step 2        # Launch step 2 (follow-ups)
  python3 vt_me_bland_campaign.py --step 3        # Launch step 3 (finals)
  python3 vt_me_bland_campaign.py --status        # Check campaign status
"""

import csv
import json
import time
import requests
import os
import sys
import argparse
from datetime import datetime

BLAND_API_KEY = os.environ.get("BLAND_API_KEY", "")
CAMPAIGN_FILE = "/app/vt_me_campaign_contacts.csv"
PROGRESS_FILE = "/app/vt_me_campaign_progress.json"

# Call config
FROM_NUMBER = "+18553218342"  # 855-321-VEGA

CALL_CONFIG = {
    "model": "enhanced",
    "voice": "maya",
    "language": "en-US",
    "max_duration": 5,
    "record": True,
    "answered_by_enabled": True,
    "voicemail_action": "leave_message",
    "metadata": {"campaign": "vt_me_outreach"}
}

SCRIPTS = {
    1: {
        "task": (
            "You are Sarah, a friendly outreach rep from Vega Apps. "
            "Call subcontractors to introduce Vega Estimating AI — an AI tool that automates "
            "takeoffs and estimating for construction subs. "
            "Goal: get them to visit vegaestimating.ai and book a free 10-minute demo. "
            "Be warm and conversational. Never pushy. Keep it under 3 minutes. "
            "If they ask for a callback number, it's 801-791-4095."
        ),
        "first_sentence": "Hey, is this someone at {{company_name}}?",
        "voicemail_message": (
            "Hey, this is Sarah from Vega Apps. I was calling about a free AI estimating tool "
            "we built for {{trade}} contractors — it automates your takeoffs and bids. "
            "Check it out at vegaestimating dot ai — you can book a free 10-minute demo right on the site. "
            "We'll try you again in a few days. Have a great day!"
        )
    },
    2: {
        "task": (
            "You are Sarah, a friendly outreach rep from Vega Apps following up on a previous call. "
            "You called a few days ago about Vega Estimating AI — an AI tool that automates "
            "takeoffs and estimating for construction subs. "
            "Goal: get them to visit vegaestimating.ai and book a free 10-minute demo. "
            "Be brief and respectful of their time. If no interest, thank them and end the call."
        ),
        "first_sentence": "Hey, this is Sarah from Vega Apps — I tried you a few days ago. Quick follow-up if you have 60 seconds?",
        "voicemail_message": (
            "Hi, Sarah again from Vega Apps — second try! "
            "Just following up on Vega Estimating AI, our free tool for {{trade}} contractors. "
            "If you want to see a quick demo, visit vegaestimating dot ai. "
            "We'll make one more attempt and then leave you alone! Have a great day."
        )
    },
    3: {
        "task": (
            "You are Sarah, a friendly outreach rep from Vega Apps making a final follow-up call. "
            "This is your last attempt to reach this subcontractor about Vega Estimating AI. "
            "Be brief, friendly, and low-pressure. If they're not interested, thank them and wish them well. "
            "Goal: book a free demo at vegaestimating.ai or at minimum leave a lasting positive impression."
        ),
        "first_sentence": "Hey, is this {{company_name}}? Sarah here from Vega Apps — last time I'll bug you, I promise!",
        "voicemail_message": (
            "Hi, it's Sarah one last time from Vega Apps. "
            "We built a free AI estimating tool for {{trade}} subs — check it out at vegaestimating dot ai. "
            "That's our last call — no pressure! Wish you a great busy season."
        )
    }
}

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

def load_contacts():
    contacts = []
    with open(CAMPAIGN_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            contacts.append(row)
    return contacts

def send_call(phone, company, trade, step):
    """Send a single call via Bland.ai."""
    script = SCRIPTS[step]

    payload = {
        **CALL_CONFIG,
        "phone_number": phone,
        "task": script["task"],
        "first_sentence": script["first_sentence"].replace("{{company_name}}", company).replace("{{trade}}", trade),
        "voicemail_message": script["voicemail_message"].replace("{{company_name}}", company).replace("{{trade}}", trade),
        "request_data": {
            "company_name": company,
            "trade": trade
        },
        "metadata": {
            **CALL_CONFIG["metadata"],
            "step": step,
            "company": company,
            "state": "VT_ME_Campaign"
        }
    }

    resp = requests.post(
        "https://api.bland.ai/v1/calls",
        headers={
            "authorization": BLAND_API_KEY,
            "Content-Type": "application/json"
        },
        json=payload
    )

    return resp.json()

def run_step(step_num, dry_run=False):
    """Launch calls for a specific step."""
    if not BLAND_API_KEY:
        print("ERROR: BLAND_API_KEY not set. Export it before running.")
        print("  export BLAND_API_KEY=your_key_here")
        return

    contacts = load_contacts()
    progress = load_progress()

    step_key = f"step_{step_num}"
    prev_step_key = f"step_{step_num - 1}"

    # For step 1: call everyone
    # For step 2+: only call those who got voicemail/no answer on previous step
    eligible = []
    for c in contacts:
        phone = c.get("Phone", "").strip()
        company = c.get("Company Name", "").strip()
        if not phone or not company:
            continue

        phone_key = ''.join(d for d in phone if d.isdigit())

        # Already called this step?
        if phone_key in progress.get(step_key, {}):
            continue

        # Step 2/3: only re-call if previous step resulted in voicemail/no answer
        if step_num > 1:
            prev_result = progress.get(prev_step_key, {}).get(phone_key, {}).get("outcome", "")
            # Skip if they answered and engaged (demo booked or said not interested)
            if prev_result in ["answered_engaged", "not_interested", "demo_booked"]:
                continue
            # Re-call if: voicemail, no_answer, unknown
            if not prev_result:
                continue  # Never called in previous step

        eligible.append(c)

    print(f"\nStep {step_num} - Eligible contacts: {len(eligible)}")
    if dry_run:
        print("DRY RUN - No calls sent. Sample:")
        for c in eligible[:5]:
            print(f"  {c['Company Name']} | {c['Phone']} | {c['Trade']}")
        return

    confirm = input(f"\nReady to send {len(eligible)} calls for Step {step_num}? (yes/no): ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return

    if step_key not in progress:
        progress[step_key] = {}

    sent = 0
    errors = 0
    batch_start = datetime.now().isoformat()

    for i, c in enumerate(eligible):
        phone = c.get("Phone", "").strip()
        company = c.get("Company Name", "").strip()
        trade = c.get("Trade", "").strip()
        phone_key = ''.join(d for d in phone if d.isdigit())

        result = send_call(phone, company, trade, step_num)

        call_id = result.get("call_id", "")
        status = result.get("status", result.get("message", "unknown"))

        progress[step_key][phone_key] = {
            "company": company,
            "phone": phone,
            "trade": trade,
            "state": c.get("State", ""),
            "call_id": call_id,
            "sent_at": datetime.now().isoformat(),
            "outcome": "pending"
        }

        if call_id:
            sent += 1
        else:
            errors += 1
            print(f"  ERROR on {company}: {result}")

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(eligible)} sent...")
            save_progress(progress)

        time.sleep(0.3)  # Rate limit

    save_progress(progress)
    print(f"\n=== Step {step_num} Complete ===")
    print(f"  Sent: {sent}")
    print(f"  Errors: {errors}")
    print(f"  Progress saved to: {PROGRESS_FILE}")
    if step_num < 3:
        days = 3 if step_num == 1 else 4
        print(f"\n  Next: Run Step {step_num+1} in {days} days.")
        print(f"  Command: python3 vt_me_bland_campaign.py --step {step_num+1}")

def show_status():
    """Show campaign progress summary."""
    progress = load_progress()
    contacts = load_contacts()
    total = len(contacts)

    print(f"\n=== VT/ME Campaign Status ===")
    print(f"Total contacts: {total}")

    for step in [1, 2, 3]:
        step_key = f"step_{step}"
        step_data = progress.get(step_key, {})
        called = len(step_data)
        pending = sum(1 for v in step_data.values() if v.get("outcome") == "pending")
        demo_booked = sum(1 for v in step_data.values() if v.get("outcome") == "demo_booked")
        not_interested = sum(1 for v in step_data.values() if v.get("outcome") == "not_interested")
        voicemail = sum(1 for v in step_data.values() if "voicemail" in v.get("outcome", ""))

        print(f"\nStep {step}:")
        print(f"  Called: {called}")
        print(f"  Demos booked: {demo_booked}")
        print(f"  Not interested: {not_interested}")
        print(f"  Voicemail: {voicemail}")
        print(f"  Pending result: {pending}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VT/ME Multistep Call Campaign")
    parser.add_argument("--step", type=int, choices=[1, 2, 3], help="Run step 1, 2, or 3")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending calls")
    parser.add_argument("--status", action="store_true", help="Show campaign status")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.step:
        run_step(args.step, dry_run=args.dry_run)
    else:
        parser.print_help()
