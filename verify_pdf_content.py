import pdfplumber
import sys

filename = r"e:\GitHub\TeachCalendar-Wizard\peiyangfangan.pdf"
search_term = "数值模拟在材料成型中的应用"

print(f"Searching for '{search_term}' in {filename}...\n")

try:
    found = False
    with pdfplumber.open(filename) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text and search_term in text:
                print(f"✅ Found in Page {i+1} Text:")
                # Print context (line containing the term)
                for line in text.split('\n'):
                    if search_term in line:
                        print(f"   Line: {line.strip()}")
                found = True
                
                # Check tables on this page
                tables = page.extract_tables()
                if tables:
                    print(f"   Page {i+1} has {len(tables)} tables.")
                    for t_idx, table in enumerate(tables):
                        # Convert table to string to search
                        t_str = str(table)
                        if search_term in t_str:
                            print(f"   ✅ Found in Table {t_idx+1}!")
                            # Print the row containing the term
                            for row in table:
                                if any(cell and search_term in cell for cell in row):
                                    print(f"   Row Data: {row}")
                                    
    if not found:
        print("❌ identifying string not found in text layer. The PDF might be scanned or use different encoding.")

except Exception as e:
    print(f"Error reading PDF: {e}")
