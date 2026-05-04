import csv

output = []
output.append("BEGIN;")

with open('C:/Users/lenovo/OneDrive/Documents/faq_questions.csv', 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    print("Columns:", header)
    
    for row in reader:
        escaped = ["'" + col.replace("'", "''") + "'" if col else 'NULL' for col in row]
        sql = f"INSERT INTO public.faq_questions VALUES ({','.join(escaped)}) ON CONFLICT DO NOTHING;"
        output.append(sql)

output.append("COMMIT;")

with open('C:/Users/lenovo/OneDrive/Documents/import_faq.sql', 'w', encoding='utf-8') as f:
    f.write('\n'.join(output))

print(f"Done! {len(output)-2} INSERT statements generated!")