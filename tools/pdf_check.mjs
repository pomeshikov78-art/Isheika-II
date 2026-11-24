/* TOOL-06. Проверка PDF-отчёта: структура, число страниц, извлечение кириллицы.
 *   npm install pdfjs-dist
 *   node tools/pdf_check.mjs var/files/<research>/report-<id>.pdf
 */
import fs from 'fs';
const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs');
const data = new Uint8Array(fs.readFileSync(process.argv[2] || '/tmp/report-test.pdf'));
const doc = await pdfjs.getDocument({data, useSystemFonts:false, standardFontDataUrl:'node_modules/pdfjs-dist/standard_fonts/'}).promise;
console.log('страниц:', doc.numPages);
for (let i=1;i<=Math.min(3,doc.numPages);i++){
  const page = await doc.getPage(i);
  const tc = await page.getTextContent();
  const text = tc.items.map(x=>x.str).join(' ').replace(/\s+/g,' ');
  console.log('--- стр.'+i+' ('+tc.items.length+' фрагментов):');
  console.log(text.slice(0,700));
}
