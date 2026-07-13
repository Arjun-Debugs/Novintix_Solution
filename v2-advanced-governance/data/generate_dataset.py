import os
import json
import random
from datetime import datetime, timedelta
from faker import Faker

def generate_data(target_dir: str = "."):
    fake = Faker()
    Faker.seed(42)
    random.seed(42)
    
    # 20 base vendor names
    base_vendors = [
        "Sundar Textiles Pvt Ltd",
        "Stark Industries LLC",
        "Wayne Enterprises Inc",
        "Globex Corporation",
        "Acme Industrial Products",
        "Umbrella BioChemicals",
        "Tyrell Nexus Corp",
        "Cyberdyne Systems Tech",
        "Oscorp Industries",
        "Soylent Green Co",
        "Hanamura Electronics",
        "Initech Software",
        "Veidt Enterprises",
        "Dunder Mifflin Paper",
        "Aperture Science Labs",
        "Prestige Worldwide",
        "Bluth Development",
        "Reynholm Industries",
        "Momcorp Robotics",
        "Vandelay Industries Solutions"
    ]
    
    # Currency symbols & codes map
    currency_formats = {
        "USD": ["${:,.2f}", "{:,.2f} USD", "${:,.0f}"],
        "EUR": ["€ {:,.2f}", "{:,.2f} EUR", "€_EU_FORMAT"],
        "GBP": ["£ {:,.2f}", "{:,.2f} GBP", "£ {:,.0f}"],
        "INR": ["₹ {:,.2f}", "{:,.2f} INR", "INR {:,.2f}"]
    }
    
    def format_amount(amount: float, currency: str) -> str:
        fmt = random.choice(currency_formats[currency])
        if fmt == "€_EU_FORMAT":
            # Format as 1,200.50 and swap chars to 1.200,50
            standard = "{:,.2f}".format(amount)
            # Use placeholders to swap
            eu_style = standard.replace(",", "TEMP").replace(".", ",").replace("TEMP", ".")
            return f"€ {eu_style}"
        return fmt.format(amount)
        
    invoices = []
    purchase_orders = []
    receipts = []
    
    # Target count: 75
    # Categories:
    # 1. Exact matches: ~14 clean matches (PO ref present, vendor exact, amounts exact, dates plausible)
    # 2. Exact matches (exact PO-number matches, clean amounts): ~10 (same as above)
    # 3. Fuzzy-vendor-only: ~15 (no PO ref on invoice, vendor has slight variant, amounts have <15% delta)
    # 4. Large amount deltas (>15%): ~10
    # 5. Quantity mismatches: ~8
    # 6. Implausible dates (invoice before PO): ~8
    # 7. Low vendor similarity (<80%): ~10
    
    for i in range(1, 76):
        po_number = f"PO-{1000 + i}"
        invoice_id = f"INV-{2000 + i}"
        receipt_id = f"REC-{3000 + i}"
        
        # Select vendor
        base_vendor = base_vendors[(i - 1) % len(base_vendors)]
        
        # Vendor variants for fuzzy matches
        vendor_variants = [
            base_vendor,
            base_vendor.replace(" Pvt Ltd", " Pvt. Ltd.").replace(" Inc", "").replace(" LLC", "").replace(" Co", "").replace(" Corp", ""),
            base_vendor.upper(),
            base_vendor.lower(),
            base_vendor.replace("Corporation", "Corp").replace("Enterprises", "Ent").replace("Industries", "Ind")
        ]
        
        po_vendor = base_vendor
        rec_vendor = base_vendor
        
        # Date generation
        base_date = datetime(2026, 7, 9) - timedelta(days=random.randint(10, 60))
        po_date = base_date.strftime("%Y-%m-%d")
        rec_date = (base_date + timedelta(days=random.randint(2, 5))).strftime("%Y-%m-%d")
        inv_date = (base_date + timedelta(days=random.randint(4, 10))).strftime("%Y-%m-%d")
        
        currency = random.choice(["USD", "EUR", "GBP", "INR"])
        amount = round(random.uniform(100.0, 5000.0), 2)
        qty = random.randint(1, 100)
        
        # Category assignment Heuristics
        if i <= 24: # Scenario 1 & 2: Clean matches (total 24)
            # Exact PO-number, clean amounts
            po_ref = po_number
            inv_vendor = base_vendor
            inv_amount = amount
            po_amount = amount
            rec_amount = amount
            inv_qty = qty
            po_qty = qty
            rec_qty = qty
            
        elif i <= 39: # Scenario 3: Fuzzy vendor only (total 15)
            po_ref = None # Force fuzzy matching fallback
            inv_vendor = random.choice(vendor_variants[1:]) # Typo'd/variant vendor name
            # Small amount delta (1% - 5%)
            delta_pct = random.uniform(0.01, 0.05)
            inv_amount = round(amount * (1.0 + delta_pct), 2)
            po_amount = amount
            rec_amount = amount
            inv_qty = qty
            po_qty = qty
            rec_qty = qty
            
        elif i <= 49: # Scenario 4: Large amount delta > 15% (total 10)
            po_ref = po_number
            inv_vendor = base_vendor
            # High mismatch
            inv_amount = round(amount * 1.25, 2)
            po_amount = amount
            rec_amount = amount
            inv_qty = qty
            po_qty = qty
            rec_qty = qty
            
        elif i <= 57: # Scenario 5: Quantity mismatch (total 8)
            po_ref = po_number
            inv_vendor = base_vendor
            inv_amount = amount
            po_amount = amount
            rec_amount = amount
            inv_qty = qty
            po_qty = qty + 15  # Mismatched quantity
            rec_qty = qty
            
        elif i <= 65: # Scenario 6: Implausible dates (total 8)
            po_ref = po_number
            inv_vendor = base_vendor
            inv_amount = amount
            po_amount = amount
            rec_amount = amount
            inv_qty = qty
            po_qty = qty
            rec_qty = qty
            # Invoice dated before PO
            inv_date = (base_date - timedelta(days=5)).strftime("%Y-%m-%d")
            
        elif i <= 75: # Scenario 7: Low vendor similarity < 80% (total 10)
            po_ref = None
            # Totally different vendor on invoice vs PO
            inv_vendor = "Random Subsidiary Limited"
            inv_amount = amount
            po_amount = amount
            rec_amount = amount
            inv_qty = qty
            po_qty = qty
            rec_qty = qty
            
        # Format amounts
        inv_amount_str = format_amount(inv_amount, currency)
        po_amount_str = format_amount(po_amount, currency)
        rec_amount_str = format_amount(rec_amount, currency)
        
        # Build records
        invoices.append({
            "invoice_id": invoice_id,
            "po_number": po_ref,
            "vendor_name": inv_vendor,
            "amount": inv_amount_str,
            "currency": currency,
            "invoice_date": inv_date,
            "quantity": inv_qty
        })
        
        purchase_orders.append({
            "po_number": po_number,
            "vendor_name": po_vendor,
            "amount": po_amount_str,
            "currency": currency,
            "po_date": po_date,
            "quantity": po_qty
        })
        
        receipts.append({
            "receipt_id": receipt_id,
            "po_number": po_number,
            "vendor_name": rec_vendor,
            "amount": rec_amount_str,
            "currency": currency,
            "receipt_date": rec_date,
            "quantity": rec_qty
        })
        
    # Write to target JSON files
    os.makedirs(os.path.join(target_dir, "data"), exist_ok=True)
    
    with open(os.path.join(target_dir, "data", "erp_a_invoices.json"), "w") as f:
        json.dump(invoices, f, indent=2)
        
    with open(os.path.join(target_dir, "data", "erp_b_purchase_orders.json"), "w") as f:
        json.dump(purchase_orders, f, indent=2)
        
    with open(os.path.join(target_dir, "data", "erp_c_receipts.json"), "w") as f:
        json.dump(receipts, f, indent=2)
        
    # Update FX Rates with GBP
    fx_rates = {
        "USD": 83.5,
        "EUR": 90.0,
        "GBP": 106.0,
        "INR": 1.0
    }
    with open(os.path.join(target_dir, "data", "fx_rates.json"), "w") as f:
        json.dump(fx_rates, f, indent=2)
        
    print(f"Dataset generated in {target_dir}/data/:")
    print(f" - erp_a_invoices.json: {len(invoices)} records")
    print(f" - erp_b_purchase_orders.json: {len(purchase_orders)} records")
    print(f" - erp_c_receipts.json: {len(receipts)} records")
    print(f" - fx_rates.json: {len(fx_rates)} currencies")

if __name__ == "__main__":
    generate_data(".")
