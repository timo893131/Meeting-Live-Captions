import hashlib
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('context_review', Path(__file__).parents[1]/'scripts/build-context-review.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReviewPageTests(unittest.TestCase):
    def report(self):
        return dict(status='pending_human_review', productionEligible=False,
                    audioSha256=hashlib.sha256(b'fake audio').hexdigest(),
                    rows=[dict(id=0, start=0.0, end=1.0,
                               rawText='說甲</script><img src=x onerror=alert(1)>',
                               suggestedText='說乙</script><img src=x onerror=alert(1)>',
                               suggestions=[dict(source='甲', suggested='乙', startCodePoint=1,
                                                 endCodePoint=2, decision='pending')])])

    def test_inline_metadata_and_visible_text_cannot_inject_html(self):
        page = module.build(self.report(), b'fake audio')
        self.assertNotIn('<img src=x', page)
        self.assertIn('&lt;img src=x', page)
        self.assertIn('\\u003c/script\\u003e', page)
        self.assertIn('value="pending"', page)
        self.assertIn('goldReferenceAvailable:false', page)

    def test_wrong_audio_and_tampered_edit_coordinates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'hash'):
            module.build(self.report(), b'other audio')
        r = self.report()
        r['rows'][0]['suggestions'][0]['startCodePoint'] = 0
        with self.assertRaisesRegex(ValueError, 'offsets'):
            module.build(r, b'fake audio')
        r = self.report()
        r['rows'][0]['suggestedText'] = 'incorrect preview'
        with self.assertRaisesRegex(ValueError, 'Preview'):
            module.build(r, b'fake audio')
        r = self.report()
        r['rows'][0]['suggestions'][0]['decision'] = 'accepted'
        with self.assertRaisesRegex(ValueError, 'pre-approved'):
            module.build(r, b'fake audio')


if __name__ == '__main__':
    unittest.main()
