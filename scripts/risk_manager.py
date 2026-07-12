
import json
import os
import sys

# --- RISK MANAGER MODULE ---
# Purpose: Hardcoded math to prevent LLM calculation errors.
# Usage: python risk_manager.py <account_balance> <risk_percent> <sl_pips>

def calculate_lot_size(balance, risk_pct, sl_pips, pip_value_per_lot=10.0):
    """
    Calculate lot size for standard account (1 lot = $10/pip on EURUSD).
    For Cent accounts, pip value is 0.10 per 0.01 lot. We adjust dynamically.
    """
    risk_amount = balance * (risk_pct / 100.0)
    
    # Heuristic: If balance < 100, assume Cent Account (0.10 per pip for 0.01 lot)
    is_cent_account = balance < 100
    effective_pip_value = 0.10 if is_cent_account else pip_value_per_lot
    
    # Formula: Lot Size = Risk Amount / (SL Pips * Pip Value per Lot)
    # Note: For cent accounts, we target 0.01 lot micro-trades
    if is_cent_account:
        # Conservative logic for survival on $10
        lot_size = max(0.01, round(risk_amount / (sl_pips * 1.0), 2))
    else:
        lot_size = round(risk_amount / (sl_pips * pip_value_per_lot), 2)
    
    return {
        "account_type": "CENT" if is_cent_account else "STANDARD",
        "risk_amount_usd": round(risk_amount, 2),
        "calculated_lot_size": lot_size,
        "sl_pips": sl_pips
    }

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python risk_manager.py <balance> <risk_pct> <sl_pips>")
        sys.exit(1)
    
    bal = float(sys.argv[1])
    risk = float(sys.argv[2])
    sl = float(sys.argv[3])
    
    result = calculate_lot_size(bal, risk, sl)
    print(json.dumps(result, indent=2))
