import httpx
import asyncio

NEON_HOST = "ep-autumn-water-an780dvv-pooler.c-6.us-east-1.aws.neon.tech"
NEON_CONN_STRING = f"postgresql://neondb_owner:npg_AgO0L6yiFPhD@{NEON_HOST}/neondb?sslmode=require"
NEON_HTTP_URL = f"https://{NEON_HOST}/sql"
HEADERS = {
    "Content-Type": "application/json",
    "Neon-Connection-String": NEON_CONN_STRING
}

# faq_documents ke INSERT statements
DOCS_SQL = """
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (89, 'd25f793dc86a4b5ebf33396a35a79460_file5.pdf', '2026-04-20 05:17:34.817751', true, 30, 'http://10.147.8.83:70/pdfs/d25f793dc86a4b5ebf33396a35a79460_file5.pdf', '2026-04-20 05:17:34.817751', 'failed', 0) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (101, '61723bf50926479da7321e20d6322df4_sportsFile1.pdf', '2026-04-23 04:51:44.263711', true, 43, 'http://10.147.8.83:70/pdfs/61723bf50926479da7321e20d6322df4_sportsFile1.pdf', '2026-04-23 04:51:44.263711', 'true', 0) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (83, '914a3787bd454b27980559afa243b326_file1.pdf', '2026-04-09 10:18:42.254655', true, 30, 'http://10.147.8.83:70/pdfs/914a3787bd454b27980559afa243b326_file1.pdf', '2026-04-09 10:18:42.254655', 'completed', 806) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (92, '69a3bd0d-c910-4d47-b74d-8813fa844cc3_faq.pdf', '2026-04-20 05:20:55.04237', true, 30, 'http://10.147.8.83:70/pdfs/69a3bd0d-c910-4d47-b74d-8813fa844cc3_faq.pdf', '2026-04-20 05:20:59.820051', 'completed', 241) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (93, 'ffc06ec4-6690-45d2-aeff-707df08dafd2_faq.pdf', '2026-04-20 05:21:41.799867', true, 30, 'http://10.147.8.83:70/pdfs/ffc06ec4-6690-45d2-aeff-707df08dafd2_faq.pdf', '2026-04-20 05:21:46.425203', 'completed', 241) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (87, 'ba9767ee0e064188b965615a7c91880f_file4.pdf', '2026-04-17 06:23:29.98338', true, 30, 'http://10.147.8.83:70/pdfs/ba9767ee0e064188b965615a7c91880f_file4.pdf', '2026-04-17 06:23:29.98338', 'completed', 1) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (94, 'eafd858f-827f-473e-bc3a-570895ce91e1_file2.pdf', '2026-04-20 05:26:03.24433', true, 30, 'http://10.147.8.83:70/pdfs/eafd858f-827f-473e-bc3a-570895ce91e1_file2.pdf', '2026-04-20 05:26:07.86766', 'completed', 4) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (88, '365a26d367804ee9afd1deaaf5547c0b_file2.pdf', '2026-04-17 06:23:41.348503', true, 30, 'http://10.147.8.83:70/pdfs/365a26d367804ee9afd1deaaf5547c0b_file2.pdf', '2026-04-17 06:23:41.348503', 'completed', 3) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (82, 'c7ce5abd800e4e698ff9c055858b68f9_file1.pdf', '2026-04-09 10:06:41.626943', true, 30, 'http://10.147.8.83:70/pdfs/c7ce5abd800e4e698ff9c055858b68f9_file1.pdf', '2026-04-09 10:06:41.626943', 'completed', 1) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (97, '14c43076-5191-45b0-93ef-386cf244fb11_file3.pdf', '2026-04-20 09:02:46.357215', true, 30, 'http://10.147.8.83:70/pdfs/14c43076-5191-45b0-93ef-386cf244fb11_file3.pdf', '2026-04-20 09:02:50.974703', 'completed', 1) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (96, '766d10ac-73ed-4b2f-a7bc-1fc8b1bd4117_file4.pdf', '2026-04-20 05:26:21.143419', true, 30, 'http://10.147.8.83:70/pdfs/766d10ac-73ed-4b2f-a7bc-1fc8b1bd4117_file4.pdf', '2026-04-20 05:26:25.768972', 'completed', 1) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (98, '92ddc375-29bd-40b5-bca8-7545223b9da8_file5.pdf', '2026-04-20 09:09:16.239104', true, 30, 'http://10.147.8.83:70/pdfs/92ddc375-29bd-40b5-bca8-7545223b9da8_file5.pdf', '2026-04-20 09:09:20.73216', 'completed', 1) ON CONFLICT (id) DO NOTHING;
INSERT INTO faq_documents (id, file_name, uploaded_at, is_active, type_id, file_path, created_at, status, total_chunks) VALUES (95, 'ce8b0b2e-3822-419a-9d2a-346e59f411c7_file4.pdf', '2026-04-20 05:26:18.645409', true, 30, 'http://10.147.8.83:70/pdfs/ce8b0b2e-3822-419a-9d2a-346e59f411c7_file4.pdf', '2026-04-20 05:26:23.273888', 'completed', 1) ON CONFLICT (id) DO NOTHING;
"""

async def run():
    async with httpx.AsyncClient() as client:

        # Step 1: faq_documents
        print("📄 faq_documents insert ho raha hai...")
        success = failed = 0
        for stmt in DOCS_SQL.strip().split('\n'):
            stmt = stmt.strip()
            if not stmt:
                continue
            r = await client.post(NEON_HTTP_URL, headers=HEADERS, json={"query": stmt}, timeout=30.0)
            if r.status_code == 200:
                success += 1
            else:
                failed += 1
                print(f"❌ {r.json().get('message')}")
        print(f"✅ faq_documents: {success} success | {failed} failed")

        # Step 2: faq_questions (file se load karo)
        print("\n❓ faq_questions insert ho raha hai...")
        with open('scripts/faq_questions.sql', 'r', encoding='utf-8') as f:
            questions_sql = f.read()

        success = failed = 0
        for stmt in questions_sql.strip().split('\n'):
            stmt = stmt.strip().strip('"')
            if not stmt or not stmt.startswith('INSERT'):
                continue
            r = await client.post(NEON_HTTP_URL, headers=HEADERS, json={"query": stmt}, timeout=30.0)
            if r.status_code == 200:
                success += 1
            else:
                failed += 1
        print(f"✅ faq_questions: {success} success | {failed} failed")

asyncio.run(run())