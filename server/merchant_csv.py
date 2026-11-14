"""Side-effect-free preview of merchant-origin CSV documents in a bounded ZIP."""
import csv
import io
import re
from decimal import Decimal, InvalidOperation
from zipfile import ZipFile, BadZipFile

ALLOWED = {"business_profile.csv", "product_catalogue.csv", "policies_faq.csv",
           "payment_methods.csv", "fulfilment_guide.csv", "operating_procedures.csv", "orders_template.csv"}
MAX_BYTES = 2 * 1024 * 1024
MAX_EXPANDED = 3 * 1024 * 1024

class MerchantCSVError(ValueError):
    pass

def rows(raw, filename):
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MerchantCSVError("UTF-8 required") from exc
    reader = csv.DictReader(io.StringIO(source, newline=""), strict=True)
    fields = reader.fieldnames
    if not fields or len(fields) > 25 or len(set(fields)) != len(fields) or any(not f or len(f) > 100 for f in fields):
        raise MerchantCSVError("Invalid or duplicate CSV columns")
    result = []
    try:
        for item in reader:
            if len(result) >= 250 or None in item or any(v is None or len(v) > 4000 for v in item.values()):
                raise MerchantCSVError("Invalid or excessive CSV rows")
            result.append(item)
    except csv.Error as exc:
        raise MerchantCSVError("Invalid CSV") from exc
    return result

def price_to_kobo(text):
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise MerchantCSVError("Invalid price") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise MerchantCSVError("Invalid NGN price")
    result = amount * 100
    if result > 1_000_000_000 or result != result.to_integral_value():
        raise MerchantCSVError("Invalid price range")
    return int(result)

def preview_bundle(payload):
    """Merchant review payload only. Never writes to SQL/Notion or authorizes staff."""
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise MerchantCSVError("Upload too large")
    documents = {}
    try:
        with ZipFile(io.BytesIO(payload)) as zipped:
            infos = zipped.infolist()
            if not infos or len(infos) > 15 or sum(i.file_size for i in infos) > MAX_EXPANDED:
                raise MerchantCSVError("Invalid archive size")
            for info in infos:
                if info.is_dir() or info.filename not in ALLOWED or info.filename in documents or info.flag_bits & 1:
                    raise MerchantCSVError("Invalid, nested, duplicate or encrypted file")
                with zipped.open(info) as handle:
                    raw = handle.read(MAX_EXPANDED + 1)
                if len(raw) > MAX_EXPANDED:
                    raise MerchantCSVError("Expanded file too large")
                documents[info.filename] = rows(raw, info.filename)
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise MerchantCSVError("Invalid ZIP") from exc
    if not documents.get("business_profile.csv"):
        raise MerchantCSVError("Missing business profile")
    profile = {}
    for row in documents["business_profile.csv"]:
        if set(row) != {"field", "value"}:
            raise MerchantCSVError("Business profile requires field,value columns")
        key = row["field"].strip()
        if key in profile:
            raise MerchantCSVError("Duplicate business field")
        profile[key] = row["value"].strip()
    if not profile.get("business_name") or profile.get("currency") != "NGN":
        raise MerchantCSVError("Missing business name or unsupported currency")
    products, skus = [], set()
    for row in documents.get("product_catalogue.csv", []):
        if not {"sku", "product_name", "price_ngn", "opening_stock"}.issubset(row):
            raise MerchantCSVError("Missing product columns")
        sku = row["sku"].strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}", sku) or sku in skus:
            raise MerchantCSVError("Invalid or duplicate SKU")
        skus.add(sku)
        try:
            stock = int(row["opening_stock"])
        except ValueError as exc:
            raise MerchantCSVError("Invalid stock") from exc
        if not 0 <= stock <= 100000 or str(stock) != row["opening_stock"].strip() or not row["product_name"].strip():
            raise MerchantCSVError("Invalid stock or product")
        products.append({"sku": sku, "name": row["product_name"].strip(),
                         "price_minor": price_to_kobo(row["price_ngn"].strip()), "opening_stock": stock,
                         "description": row.get("description", "").strip()})
    return {"business_profile": profile, "products": products,
            "policy_rows": documents.get("policies_faq.csv", []),
            "document_counts": {name: len(data) for name, data in documents.items()},
            "approved": False, "imported": False,
            "warnings": ["Require Admin preview approval before SQL import.",
                         "No staff authorization or payment verification can be sourced from CSV."]}
