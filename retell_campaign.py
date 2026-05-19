#!/usr/bin/env python3
"""
UT/AZ/ID Multistep Call Campaign - Retell AI
3-step sequence:
  Step 1: Initial call (today)
  Step 2: Follow-up 3 days later (voicemails/no answers only)
  Step 3: Final attempt 4 days after step 2

Usage:
  python3 retell_campaign.py --step 1 --dry-run   # Preview
  python3 retell_campaign.py --step 1              # Launch
  python3 retell_campaign.py --step 2
  python3 retell_campaign.py --step 3
  python3 retell_campaign.py --status              # Campaign summary
"""

import csv, json, time, requests, os, sys, argparse
from datetime import datetime

RETELL_API_KEY = os.environ.get("RETELL_API_KEY", "")
AGENT_ID = "agent_e721fd7f2e953bdcfbd9eb701f"
CAMPAIGN_FILE = "/app/ut_az_id_campaign_contacts.csv"
PROGRESS_FILE = "/app/ut_az_id_campaign_progress.json"
FROM_NUMBER = "+18553218342"  # 855-321-VEGA — update if needed

HEADERS = {
    "Authorization": f"Bearer {RETELL_API_KEY}",
    "Content-Type": "application/json"
}

STEP_CONFIGS = {
    1: {
        "label": "Initial Outreach",
        "dynamic_variables": lambda c: {
            "company_name": c.get("Company Name", "there"),
            "trade": c.get("Trade", "construction"),
            "state": c.get("State", "")
        }
    },
    2: {
        "label": "Follow-Up",
        "dynamic_variables": lambda c: {
            "company_name": c.get("Company Name", "there"),
            "trade": c.get("Trade", "construction"),
            "state": c.get("State", "")
        }
    },
    3: {
        "label": "Final Attempt",
        "dynamic_variables": lambda c: {
            "company_name": c.get("Company Name", "there"),
            "trade": c.get("Trade", "construction"),
            "state": c.get("State", "")
        }
    }
}

# Outcomes that should NOT get a follow-up call
CLOSED_OUTCOMES = {"demo_booked", "interested_callback", "not_interested", "wrong_number"}

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

def load_contacts():
    with open(CAMPAIGN_FILE) as f:
        return list(csv.DictReader(f))

def phone_key(phone):
    return ''.join(d for d in str(phone) if d.isdigit())

def send_call(contact, step_num):
    phone = contact.get("Phone", "").strip()
    dvars = STEP_CONFIGS[step_num]["dynamic_variables"](contact)

    payload = {
        "from_number": FROM_NUMBER,
        "to_number": phone if phone.startswith("+") else f"+1{phone_key(phone)}",
        "agent_id": AGENT_ID,
        "metadata": {
            "campaign": "vega_ut_az_id",
            "step": step_num,
            "company": contact.get("Company Name", ""),
            "state": contact.get("State", ""),
            "trade": contact.get("Trade", "")
        },
        "retell_llm_dynamic_variables": dvars
    }

    resp = requests.post(
        "https://api.retellai.com/v2/create-phone-call",
        headers=HEADERS,
        json=payload
    )
    return resp.json()

def run_step(step_num, dry_run=False, limit=None):
    if not RETELL_API_KEY:
        print("ERROR: RETELL_API_KEY not set.")
        return

    contacts = load_contacts()
    progress = load_progress()

    step_key = f"step_{step_num}"
    prev_step_key = f"step_{step_num - 1}"

    eligible = []
    for c in contacts:
        ph = phone_key(c.get("Phone", ""))
        if not ph:
            continue

        # Already called in this step?
        if ph in progress.get(step_key, {}):
            continue

        # Step 2/3: only re-call if previous step was voicemail/no_answer/pending
        if step_num > 1:
            prev = progress.get(prev_step_key, {}).get(ph, {})
            if not prev:
                continue  # Never called in previous step
            if prev.get("outcome") in CLOSED_OUTCOMES:
                continue  # Already resolved

        eligible.append(c)

    if limit:
        eligible = eligible[:limit]

    print(f"\nStep {step_num} ({STEP_CONFIGS[step_num]['label']}) — Eligible: {len(eligible)}")

    if dry_run:
        print("DRY RUN — sample contacts:")
        by_state = {}
        for c in eligible:
            s = c.get("State", "?")
            by_state[s] = by_state.get(s, 0) + 1
        print(f"  By state: {by_state}")
        for c in eligible[:5]:
            print(f"  {c['Company Name']} | {c['Phone']} | {c['Trade']} | {c['State']}")
        print(f"\nEstimated cost: ~${len(eligible) * 0.165:.2f} (avg 1.5 min/call @ $0.11/min)")
        return

    confirm = input(f"\nSend {len(eligible)} calls for Step {step_num}? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return

    if step_key not in progress:
        progress[step_key] = {}

    sent = errors = 0

    for i, c in enumerate(eligible):
        ph = phone_key(c.get("Phone", ""))
        result = send_call(c, step_num)

        call_id = result.get("call_id", "")
        error = result.get("message") or result.get("error", "")

        progress[step_key][ph] = {
            "company": c.get("Company Name", ""),
            "phone": c.get("Phone", ""),
            "trade": c.get("Trade", ""),
            "state": c.get("State", ""),
            "call_id": call_id,
            "sent_at": datetime.now().isoformat(),
            "outcome": "pending"
        }

        if call_id:
            sent += 1
        else:
            errors += 1
            print(f"  ERROR {c['Company Name']}: {error}")

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(eligible)} sent...")
            save_progress(progress)

        time.sleep(0.2)

    save_progress(progress)
    print(f"\n✅ Step {step_num} complete — Sent: {sent} | Errors: {errors}")
    if step_num < 3:
        days = 3 if step_num == 1 else 4
        print(f"   Run Step {step_num+1} in {days} days:")
        print(f"   python3 retell_campaign.py --step {step_num+1}")

def show_status():
    progress = load_progress()
    contacts = load_contacts()
    print(f"\n{'='*45}")
    print(f"  UT/AZ/ID Campaign Status")
    print(f"  Total contacts: {len(contacts)}")
    print(f"{'='*45}")

    for step in [1, 2, 3]:
        key = f"step_{step}"
        data = progress.get(key, {})
        if not data:
            print(f"\nStep {step}: Not started")
            continue

        outcomes = {}
        for v in data.values():
            o = v.get("outcome", "pending")
            outcomes[o] = outcomes.get(o, 0) + 1

        print(f"\nStep {step} ({STEP_CONFIGS[step]['label']}):")
        print(f"  Total called: {len(data)}")
        for outcome, count in sorted(outcomes.items()):
            print(f"  {outcome}: {count}")

    # Highlight hot leads
    all_callbacks = []
    all_demos = []
    for step in [1, 2, 3]:
        for ph, v in progress.get(f"step_{step}", {}).items():
            if v.get("outcome") == "demo_booked":
                all_demos.append(v)
            if v.get("outcome") == "interested_callback":
                all_callbacks.append(v)

    if all_demos or all_callbacks:
        print(f"\n🔥 HOT LEADS:")
        for v in all_demos:
            print(f"  [DEMO BOOKED] {v['company']} | {v['phone']}")
        for v in all_callbacks:
            print(f"  [CALLBACK] {v['company']} | {v['phone']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UT/AZ/ID Retell AI Call Campaign")
    parser.add_argument("--step", type=int, choices=[1, 2, 3])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, help="Cap number of calls (for testing)")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.step:
        run_step(args.step, dry_run=args.dry_run, limit=args.limit)
    else:
        parser.print_help()
