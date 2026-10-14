"""Expanded LaTeX syntax and editable Office Math structure regressions."""
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/local-export'))
from native_math import parse, emit, SYMBOLS, FUNCTIONS, ACCENTS, STYLES
from native_common import NativeExportError, NS

EXAMPLES = [
    r'\text{cos} x',
    r'D_{KL}(P \parallel Q) = \int P(x) \log \frac{P(x)}{Q(x)} dx',
    r'p(x) = \frac{1}{\sqrt{2 \pi \sigma^2}} \exp \left(-\frac{(x - \mu)^2}{2\sigma^2} \right)',
    r'\begin{pmatrix}a&b\\c&d\end{pmatrix}',
    r'f(x)=\begin{cases}x^2&\text{if }x\ge0\\-x&\text{otherwise}\end{cases}',
    r'\begin{aligned}a&=b+c\\d&=e\end{aligned}',
    r'\binom{n}{k}+\hat{x}+\overline{AB}+\underset{n\to\infty}{\lim}a_n',
    r'\mathbb{R}^{2}+\mathcal{L}+\vec{x}+\iint_D f(x,y)dxdy',
    r'\left\langle\begin{bmatrix}1&0\\0&1\end{bmatrix}\right\rangle',
    r'\left(x\rightarrow y\right)',
]


def output(source):
    parent = ET.Element('root')
    emit(parent, parse(source), {'fontSize': 28, 'color': '#123456'}, {}, 1)
    # Serializing catches accidental AST objects in attribute values.
    ET.fromstring(ET.tostring(parent))
    return parent


class ExpandedMathTests(unittest.TestCase):
    def test_user_examples_have_real_office_structures(self):
        for source in EXAMPLES:
            with self.subTest(source=source):
                self.assertIsNotNone(output(source).find('.//m:oMath', NS))
        text = output(EXAMPLES[0]).find('.//m:r', NS)
        self.assertEqual(text.findtext('m:t', namespaces=NS), 'cos')
        self.assertEqual(text.find('m:rPr/m:sty', NS).get('{'+NS['m']+'}val'), 'p')
        normal = output(EXAMPLES[2])
        self.assertEqual(len(normal.findall('.//m:d', NS)), 1)
        self.assertEqual(len(normal.findall('.//m:f', NS)), 2)
        self.assertEqual(len(normal.findall('.//m:rad', NS)), 1)

    def test_matrix_cells_and_cases_alignment_survive_export(self):
        matrix = output(EXAMPLES[3]).find('.//m:m', NS)
        rows = matrix.findall('m:mr', NS)
        self.assertEqual([[cell.findtext('.//m:t', namespaces=NS) for cell in row.findall('m:e', NS)] for row in rows], [['a', 'b'], ['c', 'd']])
        cases = output(EXAMPLES[4])
        self.assertEqual(cases.find('.//m:endChr', NS).get('{'+NS['m']+'}val'), '')
        self.assertEqual([e.get('{'+NS['m']+'}val') for e in cases.findall('.//m:mcJc', NS)], ['left','left'])
        aligned = output(EXAMPLES[5])
        self.assertEqual([e.get('{'+NS['m']+'}val') for e in aligned.findall('.//m:mcJc', NS)], ['right','left'])

    def test_symbols_functions_accents_and_styles_are_serializable(self):
        for command in SYMBOLS.keys() | FUNCTIONS | ACCENTS.keys() | STYLES:
            suffix = '{x_1}' if command in ACCENTS or command in STYLES else ''
            with self.subTest(command=command):
                output('\\' + command + suffix)
        for command in ['overset','underset','stackrel']:
            output('\\'+command+'{a}{b}')
        for command in ['overline','underline']:
            output('\\'+command+'{AB}')

    def test_malformed_structure_and_unsupported_commands_are_rejected(self):
        bad = [r'\left(x', r'\right)', r'\begin{matrix}a&b\\c\end{matrix}',
               r'\begin{matrix}a\end{pmatrix}', r'\begin{cases}x\end{cases}',
               r'\begin{matrix}a', r'\begin{unknown}x\end{unknown}',
               r'\text{unfinished', r'\text{\input{file}}', r'\input{file}']
        for source in bad:
            with self.subTest(source=source), self.assertRaises(NativeExportError):
                parse(source)
        for source in [r'\left('*100+'x'+r'\right)'*100,
                       r'\begin{matrix}'*100+'x'+r'\end{matrix}'*100,
                       r'\begin{matrix}'+ '&'.join('x' for _ in range(33))+r'\end{matrix}']:
            with self.assertRaises(NativeExportError):
                parse(source)

if __name__ == '__main__':
    unittest.main()
