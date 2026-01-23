from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import io
import re

class MarkdownToDocx:
    def __init__(self):
        self.doc = Document()
        self._setup_styles()

    def _setup_styles(self):
        # Base style config if needed
        style = self.doc.styles['Normal']
        font = style.font
        font.name = 'SimSun' # Default to SimSun for general compatibility
        font.size = Pt(12)
        # Setup element defaults for Chinese font rendering
        style.element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')

    def add_markdown_content(self, markdown_text):
        lines = markdown_text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            if not line:
                i += 1
                continue

            # 1. Headers
            if line.startswith('#'):
                level = len(line.split(' ')[0])
                text = line.lstrip('#').strip()
                # Limit to Heading 1-3 to avoid errors if 4+ not defined
                if level > 3: level = 3 
                self.doc.add_heading(text, level=level)
                i += 1
                continue

            # 2. Tables
            if line.startswith('|'):
                # Look ahead to see if it's a valid table (needs at least header + separate line)
                table_lines = []
                while i < len(lines) and lines[i].strip().startswith('|'):
                    table_lines.append(lines[i].strip())
                    i += 1
                
                if len(table_lines) >= 2:
                    self._parse_table(table_lines)
                else:
                    # Not a table, just text starting with |
                    self.doc.add_paragraph(line)
                continue

            # 3. List Items
            if line.startswith('- ') or line.startswith('* '):
                self.doc.add_paragraph(line[2:], style='List Bullet')
                i += 1
                continue
                
            # 4. Numbered Lists
            if re.match(r'^\d+\.', line):
                # Remove number and dot
                text = re.sub(r'^\d+\.\s*', '', line)
                self.doc.add_paragraph(text, style='List Number')
                i += 1
                continue

            # 5. Normal Text (with bold support)
            p = self.doc.add_paragraph()
            self._add_run_with_formatting(p, line)
            i += 1

    def _parse_table(self, table_lines):
        # Basic Markdown Table Parser
        # Filter out the separator line |---|---|
        data_rows = [line for line in table_lines if '---' not in line]
        
        if not data_rows: return

        # Calculate max columns
        rows = [[cell.strip() for cell in line.strip('|').split('|')] for line in data_rows]
        max_cols = max(len(r) for r in rows)
        
        table = self.doc.add_table(rows=len(rows), cols=max_cols)
        table.style = 'Table Grid'
        
        for r_idx, row_data in enumerate(rows):
            row_cells = table.rows[r_idx].cells
            for c_idx, cell_text in enumerate(row_data):
                if c_idx < len(row_cells):
                    # We can use the formatting parser here too if we want bold in tables
                    # But for now simple text
                    row_cells[c_idx].text = cell_text

    def _add_run_with_formatting(self, paragraph, text):
        # Support **Bold** parsing
        parts = re.split(r'(\*\*.*?\*\*)', text)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                run = paragraph.add_run(part[2:-2])
                run.bold = True
            else:
                paragraph.add_run(part)

    def save(self):
        bio = io.BytesIO()
        self.doc.save(bio)
        return bio.getvalue()

def create_rich_docx(text):
    if not text:
        text = "内容为空"
    converter = MarkdownToDocx()
    converter.add_markdown_content(text)
    return converter.save()
