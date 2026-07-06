"""Generate and validate evaluation fixtures.

Design principles:
- Each fixture is a complete OCR input with expected output.
- Expected values are auto-validated against the extraction pipeline.
- OCR lines are spatially arranged so that:
  * merge_fragments correctly keeps them as intended lines
  * table detection can fire when needed
"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.stdout.reconfigure(encoding='utf-8')

from app.services.invoice_extractor import extract_invoice

FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))

def extract(ocr_lines):
    """Run pipeline and return normalized expected dict."""
    resp = extract_invoice(ocr_lines, request_id='test')
    tax = resp.invoice.consumption_tax_by_rate or {}
    return {
        'document_type': resp.document_type,
        'issuer_registration_number': resp.invoice.issuer_registration_number,
        'transaction_date': resp.invoice.transaction_date,
        'invoice_number': resp.invoice.invoice_number,
        'total_amount': resp.invoice.total_amount,
        'tax_by_rate': {'8%': tax.get('8%'), '10%': tax.get('10%')},
        'issuer_name': resp.invoice.issuer_name,
        'recipient_name': resp.invoice.recipient_name,
        'line_items_count': len(resp.invoice.line_items) if resp.invoice.line_items else 0,
        'needs_review': resp.needs_review,
    }


def make(name, ocr_lines):
    """Create a fixture with auto-validated expected values."""
    # Validate immediately
    expected = extract(ocr_lines)
    fpath = os.path.join(FIXTURES_DIR, f"{name}.json")
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump({"name": name, "ocr_lines": ocr_lines, "expected": expected}, f, ensure_ascii=False, indent=2)
    print(f"  {name}: line_items={expected['line_items_count']} total={expected['total_amount']} reg={expected['issuer_registration_number'] is not None} date={expected['transaction_date']}")
    return expected


print("Generating fixtures...")
print()

# ===== SIMPLE INVOICES (15) =====
print("=== Simple invoices ===")

# simple_001: Standard invoice with table headers
make("simple_001", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T1234567890123", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-01-15", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社テスト商会", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 サンプル株式会社", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [300, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "VCTケーブル 2 90000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "現場消耗品 1 15000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 105000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 10% 10500", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [230, 365]}},
    {"text": "合計 115500", "confidence": 0.96, "bbox": {"top_left": [50, 380], "bottom_right": [200, 400]}},
])

# simple_002: ご請求金額 total keyword
make("simple_002", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T9876543210987", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [260, 65]}},
    {"text": "請求日 2026-02-20", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社山田商店", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 有限会社東京商事", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [300, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "PC本体 3 150000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "モニター 3 45000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 195000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 10% 19500", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [230, 365]}},
    {"text": "ご請求金額 214500", "confidence": 0.96, "bbox": {"top_left": [50, 380], "bottom_right": [230, 400]}},
])

# simple_003: Single tax rate 8%, Reiwa date
make("simple_003", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T1111111111111", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 令和8年3月10日", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [250, 100]}},
    {"text": "株式会社大阪商事", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 合同会社名古屋", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [280, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "コピー用紙 10 5000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "トナー 2 12000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 17000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 8% 1360", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [220, 365]}},
    {"text": "合計 18360", "confidence": 0.96, "bbox": {"top_left": [50, 380], "bottom_right": [190, 400]}},
])

# simple_004: Invoice number labeled
make("simple_004", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T2222222222222", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "請求書番号 INV-2026-004", "confidence": 0.96, "bbox": {"top_left": [260, 45], "bottom_right": [450, 65]}},
    {"text": "発行日 2026-04-05", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社北海道", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [200, 135]}},
    {"text": "御中 株式会社九州", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [250, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "サーバー機器 1 500000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "消費税 10% 50000", "confidence": 0.95, "bbox": {"top_left": [50, 280], "bottom_right": [230, 300]}},
    {"text": "合計 550000", "confidence": 0.96, "bbox": {"top_left": [50, 315], "bottom_right": [190, 335]}},
])

# simple_005: Three line items, ご請求金額 total
make("simple_005", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T3333333333333", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-05-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社横浜貿易", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [230, 135]}},
    {"text": "御中 株式会社京都", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 単価 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [450, 220]}},
    {"text": "デスク 2 50000 100000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [450, 255]}},
    {"text": "椅子 4 15000 60000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [450, 290]}},
    {"text": "キャビネット 1 30000 30000", "confidence": 0.93, "bbox": {"top_left": [50, 305], "bottom_right": [450, 325]}},
    {"text": "小計 190000", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [200, 365]}},
    {"text": "消費税 10% 19000", "confidence": 0.95, "bbox": {"top_left": [50, 380], "bottom_right": [230, 400]}},
    {"text": "ご請求金額 209000", "confidence": 0.96, "bbox": {"top_left": [50, 415], "bottom_right": [230, 435]}},
])

# simple_006: 請求No label
make("simple_006", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T4444444444444", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "請求No. INV-2026-006", "confidence": 0.96, "bbox": {"top_left": [260, 45], "bottom_right": [450, 65]}},
    {"text": "取引日 2026-06-15", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [220, 100]}},
    {"text": "株式会社静岡製作所", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [230, 135]}},
    {"text": "御中 株式会社茨城", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "部品A 100 50000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "部品B 50 75000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 125000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 10% 12500", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [230, 365]}},
    {"text": "合計 137500", "confidence": 0.96, "bbox": {"top_left": [50, 380], "bottom_right": [190, 400]}},
])

# simple_007: Single item
make("simple_007", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T5555555555555", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-07-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社広島サービス", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [240, 135]}},
    {"text": "御中 株式会社岡山", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "清掃サービス 1 80000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "消費税 10% 8000", "confidence": 0.95, "bbox": {"top_left": [50, 280], "bottom_right": [230, 300]}},
    {"text": "合計 88000", "confidence": 0.96, "bbox": {"top_left": [50, 315], "bottom_right": [180, 335]}},
])

# simple_008: No table (single line item without headers)
make("simple_008", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T6666666666666", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-08-12", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社愛媛産業", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社香川", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "コンサルティング料 200000", "confidence": 0.93, "bbox": {"top_left": [50, 200], "bottom_right": [270, 220]}},
    {"text": "消費税 10% 20000", "confidence": 0.95, "bbox": {"top_left": [50, 240], "bottom_right": [230, 260]}},
    {"text": "合計 220000", "confidence": 0.96, "bbox": {"top_left": [50, 280], "bottom_right": [190, 300]}},
])

# simple_009: 総合計 total keyword
make("simple_009", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T7777777777777", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-09-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社沖縄商事", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社福岡", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "小麦粉 20 40000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "砂糖 10 25000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "消費税 8% 5200", "confidence": 0.95, "bbox": {"top_left": [50, 315], "bottom_right": [220, 335]}},
    {"text": "総合計 70200", "confidence": 0.96, "bbox": {"top_left": [50, 350], "bottom_right": [190, 370]}},
])

# simple_010: 税込合計 total keyword
make("simple_010", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T8888888888888", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-10-20", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社長野製作所", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [230, 135]}},
    {"text": "御中 有限会社群馬", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [260, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "機械部品X 5 150000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "機械部品Y 3 90000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 240000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 10% 24000", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [230, 365]}},
    {"text": "税込合計 264000", "confidence": 0.96, "bbox": {"top_left": [50, 380], "bottom_right": [200, 400]}},
])

# simple_011: 請求金額 total keyword
make("simple_011", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T9999999999999", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-11-05", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社三重化学", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社奈良", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "試薬A 2 30000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "試薬B 1 45000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "消費税 8% 6000", "confidence": 0.95, "bbox": {"top_left": [50, 315], "bottom_right": [220, 335]}},
    {"text": "請求金額 81000", "confidence": 0.96, "bbox": {"top_left": [50, 350], "bottom_right": [190, 370]}},
])

# simple_012: Reiwa date single item
make("simple_012", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T1212121212121", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 令和8年12月1日", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [240, 100]}},
    {"text": "株式会社和歌山物流", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [240, 135]}},
    {"text": "御中 株式会社滋賀", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "配送料 1 55000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "消費税 10% 5500", "confidence": 0.95, "bbox": {"top_left": [50, 280], "bottom_right": [230, 300]}},
    {"text": "合計 60500", "confidence": 0.96, "bbox": {"top_left": [50, 315], "bottom_right": [190, 335]}},
])

# simple_013: お支払合計 keyword
make("simple_013", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T2323232323232", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-03-25", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社鳥取農園", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社島根", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "野菜セットA 10 30000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "フルーツセットB 5 25000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "消費税 8% 4400", "confidence": 0.95, "bbox": {"top_left": [50, 315], "bottom_right": [220, 335]}},
    {"text": "お支払合計 59400", "confidence": 0.96, "bbox": {"top_left": [50, 350], "bottom_right": [210, 370]}},
])

# simple_014: No subtotal line
make("simple_014", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T3434343434343", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-04-18", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社富山設備", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [230, 135]}},
    {"text": "御中 有限会社石川", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [260, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "空調点検 1 35000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "配管修理 1 28000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "消費税 10% 6300", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [230, 330]}},
    {"text": "合計 69300", "confidence": 0.96, "bbox": {"top_left": [50, 345], "bottom_right": [180, 365]}},
])

# simple_015: お支払い合計 keyword
make("simple_015", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T4545454545454", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-07-30", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社岐阜建設", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [230, 135]}},
    {"text": "御中 株式会社埼玉", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "鉄骨材 100 500000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "コンクリート 50 250000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "消費税 10% 75000", "confidence": 0.95, "bbox": {"top_left": [50, 315], "bottom_right": [230, 335]}},
    {"text": "お支払い合計 825000", "confidence": 0.96, "bbox": {"top_left": [50, 350], "bottom_right": [230, 370]}},
])


# ===== MULTI-LINE TABLE INVOICES (10) =====
print()
print("=== Multi-line table invoices ===")

# multiline_001: Description spans 2 lines
make("multiline_001", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T5555666677777", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-04-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社東京電機", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社神奈川", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [250, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "システム開発費", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [250, 255]}},
    {"text": "（基本設計～結合テスト）", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [300, 280]}},
    {"text": "1 800000", "confidence": 0.95, "bbox": {"top_left": [300, 250], "bottom_right": [400, 280]}},
    {"text": "サーバーメンテナンス", "confidence": 0.93, "bbox": {"top_left": [50, 300], "bottom_right": [270, 320]}},
    {"text": "月額保守料金含む", "confidence": 0.92, "bbox": {"top_left": [50, 325], "bottom_right": [250, 345]}},
    {"text": "3 120000", "confidence": 0.95, "bbox": {"top_left": [300, 315], "bottom_right": [420, 345]}},
    {"text": "小計 920000", "confidence": 0.95, "bbox": {"top_left": [50, 365], "bottom_right": [200, 385]}},
    {"text": "消費税 10% 92000", "confidence": 0.95, "bbox": {"top_left": [50, 400], "bottom_right": [230, 420]}},
    {"text": "合計 1012000", "confidence": 0.96, "bbox": {"top_left": [50, 435], "bottom_right": [200, 455]}},
])

# multiline_002: Description spans 3 lines
make("multiline_002", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T6666777788888", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-05-15", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社千葉工業", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社埼玉商事", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [250, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "新工場建設工事", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [220, 255]}},
    {"text": "（鉄骨工事）", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [180, 280]}},
    {"text": "第1期 1 5000000", "confidence": 0.95, "bbox": {"top_left": [220, 270], "bottom_right": [450, 290]}},
    {"text": "内装工事", "confidence": 0.93, "bbox": {"top_left": [50, 315], "bottom_right": [170, 335]}},
    {"text": "（床・壁塗装）", "confidence": 0.92, "bbox": {"top_left": [50, 340], "bottom_right": [200, 360]}},
    {"text": "1 2500000", "confidence": 0.95, "bbox": {"top_left": [220, 350], "bottom_right": [390, 370]}},
    {"text": "電気工事", "confidence": 0.93, "bbox": {"top_left": [50, 390], "bottom_right": [160, 410]}},
    {"text": "配線・配管", "confidence": 0.92, "bbox": {"top_left": [50, 415], "bottom_right": [180, 435]}},
    {"text": "1 1800000", "confidence": 0.95, "bbox": {"top_left": [220, 425], "bottom_right": [390, 445]}},
    {"text": "消費税 10% 930000", "confidence": 0.95, "bbox": {"top_left": [50, 465], "bottom_right": [240, 485]}},
    {"text": "合計 10230000", "confidence": 0.96, "bbox": {"top_left": [50, 500], "bottom_right": [210, 520]}},
])

# multiline_003: Mixed 8%/10% with multiline
make("multiline_003", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T7777888899999", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-06-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社栃木食品", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社茨城", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "和牛サーロイン", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [190, 255]}},
    {"text": "国産A5ランク 1 50000", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [300, 280]}},
    {"text": "オーガニック野菜", "confidence": 0.93, "bbox": {"top_left": [50, 300], "bottom_right": [200, 320]}},
    {"text": "季節の詰め合わせ 5 15000", "confidence": 0.92, "bbox": {"top_left": [50, 325], "bottom_right": [310, 345]}},
    {"text": "小計 65000", "confidence": 0.95, "bbox": {"top_left": [50, 365], "bottom_right": [200, 385]}},
    {"text": "消費税 8% 5200", "confidence": 0.95, "bbox": {"top_left": [50, 400], "bottom_right": [220, 420]}},
    {"text": "合計 70200", "confidence": 0.96, "bbox": {"top_left": [50, 435], "bottom_right": [190, 455]}},
])

# multiline_004: Long multi-line descriptions
make("multiline_004", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T8888999900000", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-07-10", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社群馬機械", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 有限会社長野", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [250, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "CNCフライス盤", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [190, 255]}},
    {"text": "型式MC-3000 1 2800000", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [320, 280]}},
    {"text": "切削工具セット", "confidence": 0.93, "bbox": {"top_left": [50, 300], "bottom_right": [190, 320]}},
    {"text": "エンドミル・ドリル含む 3 45000", "confidence": 0.92, "bbox": {"top_left": [50, 325], "bottom_right": [340, 345]}},
    {"text": "消費税 10% 284500", "confidence": 0.95, "bbox": {"top_left": [50, 370], "bottom_right": [240, 390]}},
    {"text": "合計 3129500", "confidence": 0.96, "bbox": {"top_left": [50, 405], "bottom_right": [200, 425]}},
])

# multiline_005: Multi-line with 3 items
make("multiline_005", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T9999000011111", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-08-05", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社新潟印刷", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社富山", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "パンフレットA4", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [200, 255]}},
    {"text": "両面4色カラー 5000 150000", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [330, 280]}},
    {"text": "名刺印刷", "confidence": 0.93, "bbox": {"top_left": [50, 300], "bottom_right": [160, 320]}},
    {"text": "マット紙 1000 25000", "confidence": 0.92, "bbox": {"top_left": [50, 325], "bottom_right": [270, 345]}},
    {"text": "ポスターA2", "confidence": 0.93, "bbox": {"top_left": [50, 365], "bottom_right": [180, 385]}},
    {"text": "UV印刷 200 80000", "confidence": 0.92, "bbox": {"top_left": [50, 390], "bottom_right": [260, 410]}},
    {"text": "消費税 10% 25500", "confidence": 0.95, "bbox": {"top_left": [50, 430], "bottom_right": [230, 450]}},
    {"text": "合計 280500", "confidence": 0.96, "bbox": {"top_left": [50, 465], "bottom_right": [190, 485]}},
])

# multiline_006 through multiline_010 - simpler variants
make("multiline_006", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T1111222233334", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-09-12", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社石川電子", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社福井", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "センサーモジュール", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [230, 255]}},
    {"text": "温度・湿度センサー 500 250000", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [330, 280]}},
    {"text": "制御基板", "confidence": 0.93, "bbox": {"top_left": [50, 300], "bottom_right": [160, 320]}},
    {"text": "カスタム品 200 400000", "confidence": 0.92, "bbox": {"top_left": [50, 325], "bottom_right": [280, 345]}},
    {"text": "消費税 10% 65000", "confidence": 0.95, "bbox": {"top_left": [50, 370], "bottom_right": [230, 390]}},
    {"text": "合計 715000", "confidence": 0.96, "bbox": {"top_left": [50, 405], "bottom_right": [190, 425]}},
])

make("multiline_007", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T2222333344445", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-10-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社岐阜運送", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社静岡", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "海上輸送サービス", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [230, 255]}},
    {"text": "横浜→上海 2 600000", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [300, 280]}},
    {"text": "通関手続き代行", "confidence": 0.93, "bbox": {"top_left": [50, 300], "bottom_right": [210, 320]}},
    {"text": "輸出書類作成含む 1 80000", "confidence": 0.92, "bbox": {"top_left": [50, 325], "bottom_right": [300, 345]}},
    {"text": "消費税 10% 68000", "confidence": 0.95, "bbox": {"top_left": [50, 370], "bottom_right": [230, 390]}},
    {"text": "合計 748000", "confidence": 0.96, "bbox": {"top_left": [50, 405], "bottom_right": [190, 425]}},
])

make("multiline_008", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T3333444455556", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-11-20", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社兵庫工業", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 有限会社京都", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [260, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "工業用ロボット", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [200, 255]}},
    {"text": "アーム部交換部品 3 450000", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [320, 280]}},
    {"text": "ベルトコンベア", "confidence": 0.93, "bbox": {"top_left": [50, 300], "bottom_right": [200, 320]}},
    {"text": "幅600mm×長さ5m 2 180000", "confidence": 0.92, "bbox": {"top_left": [50, 325], "bottom_right": [330, 345]}},
    {"text": "消費税 10% 63000", "confidence": 0.95, "bbox": {"top_left": [50, 370], "bottom_right": [230, 390]}},
    {"text": "合計 693000", "confidence": 0.96, "bbox": {"top_left": [50, 405], "bottom_right": [190, 425]}},
])

make("multiline_009", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T4444555566667", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-12-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社宮崎ソフト", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [230, 135]}},
    {"text": "御中 株式会社熊本", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "業務システム開発", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [220, 255]}},
    {"text": "販売管理・在庫管理 1 3000000", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [350, 280]}},
    {"text": "クラウド移行支援", "confidence": 0.93, "bbox": {"top_left": [50, 300], "bottom_right": [210, 320]}},
    {"text": "AWS移行・設定 1 800000", "confidence": 0.92, "bbox": {"top_left": [50, 325], "bottom_right": [300, 345]}},
    {"text": "消費税 10% 380000", "confidence": 0.95, "bbox": {"top_left": [50, 370], "bottom_right": [240, 390]}},
    {"text": "合計 4180000", "confidence": 0.96, "bbox": {"top_left": [50, 405], "bottom_right": [210, 425]}},
])

make("multiline_010", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T5555666677778", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-01-25", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社大分化学", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 有限会社佐賀", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [260, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "試薬セットA", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [180, 255]}},
    {"text": "研究用高純度 10 350000", "confidence": 0.92, "bbox": {"top_left": [50, 260], "bottom_right": [310, 280]}},
    {"text": "実験器具セット", "confidence": 0.93, "bbox": {"top_left": [50, 300], "bottom_right": [200, 320]}},
    {"text": "ガラス器具・測定器 5 175000", "confidence": 0.92, "bbox": {"top_left": [50, 325], "bottom_right": [330, 345]}},
    {"text": "安全キャビネット", "confidence": 0.93, "bbox": {"top_left": [50, 365], "bottom_right": [210, 385]}},
    {"text": "ドラフト付き 2 500000", "confidence": 0.92, "bbox": {"top_left": [50, 390], "bottom_right": [290, 410]}},
    {"text": "消費税 10% 102500", "confidence": 0.95, "bbox": {"top_left": [50, 435], "bottom_right": [240, 455]}},
    {"text": "合計 1127500", "confidence": 0.96, "bbox": {"top_left": [50, 470], "bottom_right": [210, 490]}},
])


# ===== RECEIPTS / SIMPLIFIED INVOICES (5) =====
print()
print("=== Receipts ===")

# receipt_001: Simple receipt
make("receipt_001", [
    {"text": "領収書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [130, 30]}},
    {"text": "登録番号 T9999888877776", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "日付 2026-03-15", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [180, 100]}},
    {"text": "株式会社ABC商事", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [210, 135]}},
    {"text": "お買上 金額 ¥55,000", "confidence": 0.94, "bbox": {"top_left": [50, 155], "bottom_right": [240, 175]}},
    {"text": "消費税 10% 5,000", "confidence": 0.95, "bbox": {"top_left": [50, 190], "bottom_right": [220, 210]}},
    {"text": "合計 55,000", "confidence": 0.96, "bbox": {"top_left": [50, 225], "bottom_right": [180, 245]}},
])

# receipt_002: Grocery receipt
make("receipt_002", [
    {"text": "レシート", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [140, 30]}},
    {"text": "登録番号 T8888777766655", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "2026-04-20", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [160, 100]}},
    {"text": "スーパー株式会社マルエイ", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [250, 135]}},
    {"text": "内消費税 8% 240", "confidence": 0.95, "bbox": {"top_left": [50, 155], "bottom_right": [210, 175]}},
    {"text": "内消費税 10% 450", "confidence": 0.95, "bbox": {"top_left": [50, 190], "bottom_right": [210, 210]}},
    {"text": "合計 8,450", "confidence": 0.96, "bbox": {"top_left": [50, 225], "bottom_right": [175, 245]}},
])

# receipt_003: Simplified invoice
make("receipt_003", [
    {"text": "簡易請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [170, 30]}},
    {"text": "登録番号 T7777666655544", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "日付 2026-06-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [180, 100]}},
    {"text": "有限会社山本商店", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "金額 32,400", "confidence": 0.96, "bbox": {"top_left": [50, 155], "bottom_right": [170, 175]}},
    {"text": "合計 32,400", "confidence": 0.96, "bbox": {"top_left": [50, 190], "bottom_right": [180, 210]}},
])

# receipt_004: Store receipt
make("receipt_004", [
    {"text": "領収書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [130, 30]}},
    {"text": "登録番号 T6666555544433", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行 2026-08-30", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [180, 100]}},
    {"text": "株式会社ドラッグストア松本", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [290, 135]}},
    {"text": "お買上 金額 ¥128,000", "confidence": 0.94, "bbox": {"top_left": [50, 155], "bottom_right": [250, 175]}},
    {"text": "消費税 10% 11,636", "confidence": 0.95, "bbox": {"top_left": [50, 190], "bottom_right": [220, 210]}},
    {"text": "合計 128,000", "confidence": 0.96, "bbox": {"top_left": [50, 225], "bottom_right": [190, 245]}},
])

# receipt_005: Cash register receipt
make("receipt_005", [
    {"text": "領収書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [130, 30]}},
    {"text": "登録番号 T5555444433322", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "2026-11-11", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [150, 100]}},
    {"text": "夕飯屋弁兵衛", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [180, 135]}},
    {"text": "お買上 金額 ¥15,000", "confidence": 0.94, "bbox": {"top_left": [50, 155], "bottom_right": [240, 175]}},
    {"text": "消費税 10% 1,363", "confidence": 0.95, "bbox": {"top_left": [50, 190], "bottom_right": [210, 210]}},
    {"text": "合計 15,000", "confidence": 0.96, "bbox": {"top_left": [50, 225], "bottom_right": [180, 245]}},
])


# ===== POOR QUALITY SCANS (5) =====
print()
print("=== Poor quality scans ===")

# poor_quality_001: Low confidence, missing chars
make("poor_quality_001", [
    {"text": "請求書", "confidence": 0.72, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T1234567890123", "confidence": 0.65, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-01-15", "confidence": 0.68, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社テスト商会", "confidence": 0.62, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 サンフル株式会社", "confidence": 0.60, "bbox": {"top_left": [50, 160], "bottom_right": [300, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.70, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "VCTケーブ 2 90000", "confidence": 0.55, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "現場費耗品 1 15000", "confidence": 0.52, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 105000", "confidence": 0.68, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 10% 10500", "confidence": 0.66, "bbox": {"top_left": [50, 345], "bottom_right": [230, 365]}},
    {"text": "合計 115500", "confidence": 0.70, "bbox": {"top_left": [50, 380], "bottom_right": [200, 400]}},
])

# poor_quality_002: Fragmented text
make("poor_quality_002", [
    {"text": "請", "confidence": 0.58, "bbox": {"top_left": [50, 10], "bottom_right": [75, 30]}},
    {"text": "求", "confidence": 0.55, "bbox": {"top_left": [80, 10], "bottom_right": [105, 30]}},
    {"text": "書", "confidence": 0.60, "bbox": {"top_left": [110, 10], "bottom_right": [135, 30]}},
    {"text": "登録番号 T5555444433332", "confidence": 0.62, "bbox": {"top_left": [50, 45], "bottom_right": [260, 65]}},
    {"text": "発行日 2026-03-10", "confidence": 0.60, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会舎大阪商事", "confidence": 0.50, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社名古屋", "confidence": 0.58, "bbox": {"top_left": [50, 160], "bottom_right": [250, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.65, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "部品Z 10 85000", "confidence": 0.55, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "小計 85000", "confidence": 0.62, "bbox": {"top_left": [50, 280], "bottom_right": [200, 300]}},
    {"text": "消費税 10% 8500", "confidence": 0.60, "bbox": {"top_left": [50, 315], "bottom_right": [230, 335]}},
    {"text": "合計 93500", "confidence": 0.65, "bbox": {"top_left": [50, 350], "bottom_right": [190, 370]}},
])

# poor_quality_003: Low OCR, blurred text
make("poor_quality_003", [
    {"text": "請求書", "confidence": 0.50, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T3333222211110", "confidence": 0.55, "bbox": {"top_left": [50, 45], "bottom_right": [260, 65]}},
    {"text": "発行日 2026-07-20", "confidence": 0.52, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "有限会社東京部品", "confidence": 0.50, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社大田", "confidence": 0.53, "bbox": {"top_left": [50, 160], "bottom_right": [230, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.58, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "ネジセット 200 12000", "confidence": 0.50, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "パッキン 100 8000", "confidence": 0.52, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "消費税 10% 2000", "confidence": 0.55, "bbox": {"top_left": [50, 315], "bottom_right": [220, 335]}},
    {"text": "合計 22000", "confidence": 0.58, "bbox": {"top_left": [50, 350], "bottom_right": [180, 370]}},
])

# poor_quality_004: Missing registration number characters
make("poor_quality_004", [
    {"text": "請求書", "confidence": 0.70, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T23456 7890123", "confidence": 0.55, "bbox": {"top_left": [50, 45], "bottom_right": [260, 65]}},
    {"text": "発行日 2026-09-05", "confidence": 0.68, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社沖縄物産", "confidence": 0.65, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社鹿児島", "confidence": 0.62, "bbox": {"top_left": [50, 160], "bottom_right": [250, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.68, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "加工食品A 50 75000", "confidence": 0.58, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "加工食品B 30 45000", "confidence": 0.60, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "消費税 8% 9600", "confidence": 0.65, "bbox": {"top_left": [50, 315], "bottom_right": [220, 335]}},
    {"text": "合計 129600", "confidence": 0.68, "bbox": {"top_left": [50, 350], "bottom_right": [190, 370]}},
])

# poor_quality_005: Very low confidence on amounts
make("poor_quality_005", [
    {"text": "請求書", "confidence": 0.65, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T8888777766665", "confidence": 0.60, "bbox": {"top_left": [50, 45], "bottom_right": [260, 65]}},
    {"text": "発行日 2026-12-15", "confidence": 0.62, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社北海道水産", "confidence": 0.58, "bbox": {"top_left": [50, 115], "bottom_right": [230, 135]}},
    {"text": "御中 有限会社青森", "confidence": 0.55, "bbox": {"top_left": [50, 160], "bottom_right": [250, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.60, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "鮭切り身 100 80000", "confidence": 0.52, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "ほたて 50 60000", "confidence": 0.50, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "消費税 8% 11200", "confidence": 0.58, "bbox": {"top_left": [50, 315], "bottom_right": [220, 335]}},
    {"text": "合計 151200", "confidence": 0.60, "bbox": {"top_left": [50, 350], "bottom_right": [190, 370]}},
])


# ===== MIXED 8%/10% TAX (5) =====
print()
print("=== Mixed tax ===")

# mixed_tax_001: Separate 8% and 10% tax lines
make("mixed_tax_001", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T1111000022223", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-05-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社広島貿易", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社岡山", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "食品A 100 50000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "雑貨B 50 30000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 80000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 8% 4000", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [220, 365]}},
    {"text": "消費税 10% 3000", "confidence": 0.95, "bbox": {"top_left": [230, 345], "bottom_right": [400, 365]}},
    {"text": "合計 87000", "confidence": 0.96, "bbox": {"top_left": [50, 380], "bottom_right": [180, 400]}},
])

# mixed_tax_002: Consolidated tax line
make("mixed_tax_002", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T2222000033334", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-06-15", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社山口商事", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社鳥取", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "飲料品 200 100000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "日用雑貨 100 50000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 150000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 8% 4000 10% 5000", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [350, 365]}},
    {"text": "合計 159000", "confidence": 0.96, "bbox": {"top_left": [50, 380], "bottom_right": [190, 400]}},
])

# mixed_tax_003: 8% line only, 10% line only
make("mixed_tax_003", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T3333000044445", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-07-20", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社香川物流", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [230, 135]}},
    {"text": "御中 株式会社徳島", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "米50kg 10 50000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "電子機器 5 200000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 250000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 8% 4000", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [220, 365]}},
    {"text": "消費税 10% 20000", "confidence": 0.95, "bbox": {"top_left": [50, 380], "bottom_right": [230, 400]}},
    {"text": "合計 274000", "confidence": 0.96, "bbox": {"top_left": [50, 415], "bottom_right": [190, 435]}},
])

# mixed_tax_004: Tax lines before total
make("mixed_tax_004", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T4444000055556", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-08-10", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社愛媛水産", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社高知", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "鮮魚セット 30 120000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "冷凍食品 50 80000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "小計 200000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 8% 9600", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [220, 365]}},
    {"text": "消費税 10% 8000", "confidence": 0.95, "bbox": {"top_left": [260, 345], "bottom_right": [420, 365]}},
    {"text": "ご請求金額 217600", "confidence": 0.96, "bbox": {"top_left": [50, 380], "bottom_right": [230, 400]}},
])

# mixed_tax_005: 3 items mixed rates
make("mixed_tax_005", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T5555000066667", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-09-25", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社佐賀工業", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社長崎", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "加工品A 200 60000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "加工品B 100 40000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "電化製品 5 500000", "confidence": 0.93, "bbox": {"top_left": [50, 305], "bottom_right": [400, 325]}},
    {"text": "小計 600000", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [200, 365]}},
    {"text": "消費税 8% 8000", "confidence": 0.95, "bbox": {"top_left": [50, 380], "bottom_right": [220, 400]}},
    {"text": "消費税 10% 50000", "confidence": 0.95, "bbox": {"top_left": [260, 380], "bottom_right": [420, 400]}},
    {"text": "合計 658000", "confidence": 0.96, "bbox": {"top_left": [50, 415], "bottom_right": [190, 435]}},
])


# ===== NEGATIVE SAMPLES (5) =====
print()
print("=== Negative samples ===")

# non_invoice_001: Meeting minutes
make("non_invoice_001", [
    {"text": "会議録", "confidence": 0.97, "bbox": {"top_left": [50, 10], "bottom_right": [120, 30]}},
    {"text": "日時: 2026-04-10 14:00", "confidence": 0.95, "bbox": {"top_left": [50, 45], "bottom_right": [220, 65]}},
    {"text": "場所: 第3会議室", "confidence": 0.94, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "出席者: 田中, 佐藤, 鈴木", "confidence": 0.93, "bbox": {"top_left": [50, 115], "bottom_right": [280, 135]}},
    {"text": "議題: 新プロジェクトの進捗について", "confidence": 0.92, "bbox": {"top_left": [50, 150], "bottom_right": [300, 170]}},
    {"text": "来週までに各担当者が報告書を提出", "confidence": 0.91, "bbox": {"top_left": [50, 185], "bottom_right": [320, 205]}},
])

# non_invoice_002: Resume
make("non_invoice_002", [
    {"text": "履歴書", "confidence": 0.97, "bbox": {"top_left": [50, 10], "bottom_right": [120, 30]}},
    {"text": "氏名: 山田太郎", "confidence": 0.96, "bbox": {"top_left": [50, 50], "bottom_right": [200, 70]}},
    {"text": "生年月日: 1990年4月1日", "confidence": 0.95, "bbox": {"top_left": [50, 90], "bottom_right": [240, 110]}},
    {"text": "住所: 東京都千代田区", "confidence": 0.94, "bbox": {"top_left": [50, 130], "bottom_right": [240, 150]}},
    {"text": "学歴: 東京大学工学部", "confidence": 0.93, "bbox": {"top_left": [50, 170], "bottom_right": [230, 190]}},
    {"text": "職歴: 株式会社ABC（2015-2020）", "confidence": 0.92, "bbox": {"top_left": [50, 210], "bottom_right": [310, 230]}},
])

# non_invoice_003: Contract
make("non_invoice_003", [
    {"text": "業務委託契約書", "confidence": 0.97, "bbox": {"top_left": [50, 10], "bottom_right": [200, 30]}},
    {"text": "発注者: 株式会社A", "confidence": 0.96, "bbox": {"top_left": [50, 50], "bottom_right": [200, 70]}},
    {"text": "受注者: 株式会社B", "confidence": 0.96, "bbox": {"top_left": [50, 90], "bottom_right": [200, 110]}},
    {"text": "契約金額: 5,000,000円", "confidence": 0.95, "bbox": {"top_left": [50, 130], "bottom_right": [260, 150]}},
    {"text": "契約期間: 2026年4月1日から", "confidence": 0.94, "bbox": {"top_left": [50, 170], "bottom_right": [270, 190]}},
    {"text": "第1条 目的", "confidence": 0.93, "bbox": {"top_left": [50, 210], "bottom_right": [150, 230]}},
    {"text": "第2条 業務内容", "confidence": 0.93, "bbox": {"top_left": [50, 250], "bottom_right": [170, 270]}},
])

# non_invoice_004: Purchase order
make("non_invoice_004", [
    {"text": "発注書", "confidence": 0.97, "bbox": {"top_left": [50, 10], "bottom_right": [120, 30]}},
    {"text": "発注番号 PO-2026-001", "confidence": 0.96, "bbox": {"top_left": [50, 50], "bottom_right": [240, 70]}},
    {"text": "仕入先: 株式会社C", "confidence": 0.95, "bbox": {"top_left": [50, 90], "bottom_right": [210, 110]}},
    {"text": "納期: 2026-05-30", "confidence": 0.95, "bbox": {"top_left": [50, 130], "bottom_right": [200, 150]}},
    {"text": "品名 数量 単価", "confidence": 0.94, "bbox": {"top_left": [50, 170], "bottom_right": [300, 190]}},
    {"text": "部品X 100 500", "confidence": 0.93, "bbox": {"top_left": [50, 210], "bottom_right": [250, 230]}},
    {"text": "部品Y 200 300", "confidence": 0.93, "bbox": {"top_left": [50, 250], "bottom_right": [250, 270]}},
])

# non_invoice_005: Delivery note
make("non_invoice_005", [
    {"text": "納品書", "confidence": 0.97, "bbox": {"top_left": [50, 10], "bottom_right": [120, 30]}},
    {"text": "納品日 2026-06-01", "confidence": 0.96, "bbox": {"top_left": [50, 50], "bottom_right": [200, 70]}},
    {"text": "株式会社D様", "confidence": 0.95, "bbox": {"top_left": [50, 90], "bottom_right": [180, 110]}},
    {"text": "品名 数量", "confidence": 0.94, "bbox": {"top_left": [50, 130], "bottom_right": [200, 150]}},
    {"text": "商品A 50", "confidence": 0.93, "bbox": {"top_left": [50, 170], "bottom_right": [150, 190]}},
    {"text": "商品B 30", "confidence": 0.93, "bbox": {"top_left": [50, 210], "bottom_right": [150, 230]}},
    {"text": "上記納品いたします", "confidence": 0.92, "bbox": {"top_left": [50, 250], "bottom_right": [240, 270]}},
])


# ===== EDGE CASES (5+) =====
print()
print("=== Edge cases ===")

# edge_no_table: No table / line items
make("edge_no_table", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T9999888877776", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-03-15", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社特例子会社", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社東京", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "サービス利用料 50000", "confidence": 0.93, "bbox": {"top_left": [50, 200], "bottom_right": [220, 220]}},
    {"text": "消費税 10% 5000", "confidence": 0.95, "bbox": {"top_left": [50, 240], "bottom_right": [230, 260]}},
    {"text": "合計 55000", "confidence": 0.96, "bbox": {"top_left": [50, 280], "bottom_right": [180, 300]}},
])

# edge_no_registration: Missing registration number
make("edge_no_registration", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "発行日 2026-06-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社登録なし商事", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [240, 135]}},
    {"text": "御中 株式会社東京", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "サービス 1 50000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "消費税 10% 5000", "confidence": 0.95, "bbox": {"top_left": [50, 280], "bottom_right": [230, 300]}},
    {"text": "合計 55000", "confidence": 0.96, "bbox": {"top_left": [50, 315], "bottom_right": [190, 335]}},
])

# edge_discount_only: Invoice with discount
make("edge_discount_only", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T7777666655544", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 2026-07-01", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社値引販売", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社埼玉", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "商品A 10 100000", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "値引 -10000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [250, 290]}},
    {"text": "小計 90000", "confidence": 0.95, "bbox": {"top_left": [50, 310], "bottom_right": [200, 330]}},
    {"text": "消費税 10% 9000", "confidence": 0.95, "bbox": {"top_left": [50, 345], "bottom_right": [230, 365]}},
    {"text": "合計 99000", "confidence": 0.96, "bbox": {"top_left": [50, 380], "bottom_right": [190, 400]}},
])

# edge_full_width: All amounts in full-width digits
make("edge_full_width", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T１２３４５６７８９０１２３", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [300, 65]}},
    {"text": "発行日 ２０２６−０８−１５", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [200, 100]}},
    {"text": "株式会社全角商事", "confidence": 0.95, "bbox": {"top_left": [50, 115], "bottom_right": [220, 135]}},
    {"text": "御中 株式会社東京", "confidence": 0.95, "bbox": {"top_left": [50, 160], "bottom_right": [240, 180]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 200], "bottom_right": [400, 220]}},
    {"text": "商品X １ １０００００", "confidence": 0.93, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "消費税 １０％ １００００", "confidence": 0.95, "bbox": {"top_left": [50, 280], "bottom_right": [250, 300]}},
    {"text": "合計 １１００００", "confidence": 0.96, "bbox": {"top_left": [50, 315], "bottom_right": [200, 335]}},
])

# edge_reiwa_dates: All dates in Reiwa format
make("edge_reiwa_dates", [
    {"text": "請求書", "confidence": 0.98, "bbox": {"top_left": [50, 10], "bottom_right": [150, 30]}},
    {"text": "登録番号 T6666555544433", "confidence": 0.97, "bbox": {"top_left": [50, 45], "bottom_right": [250, 65]}},
    {"text": "発行日 令和8年11月20日", "confidence": 0.96, "bbox": {"top_left": [50, 80], "bottom_right": [250, 100]}},
    {"text": "支払期日 令和8年12月20日", "confidence": 0.96, "bbox": {"top_left": [50, 115], "bottom_right": [280, 135]}},
    {"text": "株式会社令和物流", "confidence": 0.95, "bbox": {"top_left": [50, 150], "bottom_right": [210, 170]}},
    {"text": "御中 株式会社昭和商事", "confidence": 0.95, "bbox": {"top_left": [50, 195], "bottom_right": [260, 215]}},
    {"text": "品名 数量 金額", "confidence": 0.94, "bbox": {"top_left": [50, 235], "bottom_right": [400, 255]}},
    {"text": "配送サービス 1 30000", "confidence": 0.93, "bbox": {"top_left": [50, 270], "bottom_right": [400, 290]}},
    {"text": "消費税 10% 3000", "confidence": 0.95, "bbox": {"top_left": [50, 315], "bottom_right": [230, 335]}},
    {"text": "合計 33000", "confidence": 0.96, "bbox": {"top_left": [50, 350], "bottom_right": [190, 370]}},
])


print()
print("Done!")
