import io
from zipfile import ZipFile
import pytest
from server.merchant_csv import MerchantCSVError, preview_bundle

def zipfiles(items):
    out = io.BytesIO()
    with ZipFile(out, "w") as z:
        for filename, content in items.items():
            z.writestr(filename, content)
    return out.getvalue()

def test_preview_only_and_correct_kobo_conversion():
    raw=zipfiles({"business_profile.csv":"field,value\nbusiness_name,ASYAN SHOP\ncurrency,NGN\n",
                  "product_catalogue.csv":"sku,product_name,price_ngn,opening_stock\ncup-choc,Chocolate cupcake,2500,14\nbrownie,Brownie box,6500,5\n",
                  "orders_template.csv":"order_reference,payment_status\n"})
    parsed=preview_bundle(raw)
    assert parsed["business_profile"]["business_name"]=="ASYAN SHOP"
    assert [p["price_minor"] for p in parsed["products"]]==[250000,650000]
    assert not parsed["approved"] and not parsed["imported"]
    assert parsed["document_counts"]["orders_template.csv"]==0

def test_disallow_zip_traversal():
    with pytest.raises(MerchantCSVError):
        preview_bundle(zipfiles({"business_profile.csv":"field,value\nbusiness_name,ASYAN SHOP\ncurrency,NGN\n","../evil.csv":"x"}))

def test_bad_currency_fails():
    with pytest.raises(MerchantCSVError):
        preview_bundle(zipfiles({"business_profile.csv":"field,value\nbusiness_name,ASYAN SHOP\ncurrency,USD\n"}))

def test_negative_product_price_fails():
    with pytest.raises(MerchantCSVError):
        preview_bundle(zipfiles({"business_profile.csv":"field,value\nbusiness_name,ASYAN SHOP\ncurrency,NGN\n",
                                  "product_catalogue.csv":"sku,product_name,price_ngn,opening_stock\nchoc,Chocolate cupcake,-3,2\n"}))
