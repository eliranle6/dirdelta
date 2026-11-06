import os
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image

from dirdelta import images
from dirdelta import localdiskdirtree


def decoded(image):
    """(width, height, [(r, g, b)]) of an images.encoded() image"""
    width, height, pixels = image.split(' ')
    data = bytes.fromhex(pixels)
    return int(width), int(height), [tuple(data[i:i + 3]) for i in range(0, len(data), 3)]


class ImagesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def write(self, name, image, **options):
        path = os.path.join(self.dir, name)
        image.save(path, **options)
        return path

    def test_a_photo_is_made_to_fit_keeping_its_proportions(self):
        path = self.write('red.jpg', Image.new('RGB', (400, 200), (255, 0, 0)))
        width, height, pixels = decoded(images.of_local_file(path, 40, 40))
        self.assertEqual((width, height), (40, 20))
        self.assertEqual(len(pixels), 40 * 20)
        red, green, blue = pixels[0]
        self.assertGreater(red, 240)
        self.assertLess(max(green, blue), 15)

    def test_a_small_one_is_kept_as_it_is(self):
        path = self.write('dot.png', Image.new('RGB', (3, 2), (0, 0, 255)))
        self.assertEqual(images.of_local_file(path, 40, 40), '3 2 ' + '0000ff' * 6)

    def test_transparency_is_on_black(self):
        path = self.write('clear.png', Image.new('RGBA', (2, 1), (255, 255, 255, 0)))
        self.assertEqual(images.of_local_file(path, 40, 40), '2 1 ' + '000000' * 2)

    def test_its_exif_orientation_is_followed(self):
        image = Image.new('RGB', (40, 20), (0, 255, 0))
        exif = image.getexif()
        # Rotated 90 degrees: shown upright, it's 20 wide and 40 high
        exif[0x0112] = 6
        path = self.write('turned.jpg', image, exif=exif)
        width, height, _ = decoded(images.of_local_file(path, 100, 100))
        self.assertEqual((width, height), (20, 40))

    def test_what_isnt_a_picture_has_none(self):
        text = os.path.join(self.dir, 'notes.txt')
        with open(text, 'w') as f:
            f.write('hi')
        self.assertIsNone(images.of_local_file(text, 40, 40))
        broken = os.path.join(self.dir, 'broken.jpg')
        with open(broken, 'wb') as f:
            f.write(b'not a jpeg')
        self.assertIsNone(images.of_local_file(broken, 40, 40))
        self.assertIsNone(images.of_local_file(os.path.join(self.dir, 'gone.jpg'), 40, 40))
        os.mkdir(os.path.join(self.dir, 'dir.jpg'))
        self.assertIsNone(images.of_local_file(os.path.join(self.dir, 'dir.jpg'), 40, 40))

    def test_a_big_file_isnt_read(self):
        path = self.write('red.png', Image.new('RGB', (4, 4), (255, 0, 0)))
        with mock.patch.object(images, 'MAX_FILE_BYTES', 10):
            self.assertIsNone(images.of_local_file(path, 40, 40))

    @unittest.skipIf(shutil.which('pdftoppm') is None, "needs pdftoppm")
    def test_a_pdfs_first_page(self):
        path = self.write('doc.pdf', Image.new('RGB', (100, 200), (255, 255, 255)))
        width, height, pixels = decoded(images.of_local_file(path, 30, 30))
        self.assertEqual(height, 30)
        self.assertLessEqual(width, 16)
        self.assertGreater(min(pixels[0]), 245)

    def test_without_pdftoppm_a_pdf_has_none(self):
        path = self.write('doc.pdf', Image.new('RGB', (10, 10)))
        with mock.patch('shutil.which', return_value=None):
            self.assertIsNone(images.of_local_file(path, 30, 30))

    def test_of_data(self):
        path = self.write('dot.png', Image.new('RGB', (1, 1), (1, 2, 3)))
        with open(path, 'rb') as f:
            self.assertEqual(images.of_data(f.read(), 10, 10), '1 1 010203')
        self.assertIsNone(images.of_data(b'', 10, 10))
        self.assertIsNone(images.of_data(b'junk', 10, 10))

    def test_of_a_local_replica(self):
        os.mkdir(os.path.join(self.dir, 'sub'))
        self.write('sub/dot.png', Image.new('RGB', (1, 1), (1, 2, 3)))
        tree = localdiskdirtree.LocalDiskDirTree(self.dir, True)
        self.assertEqual(images.of_replica(tree)('sub/dot.png', 10, 10), '1 1 010203')

    def test_of_a_drive_replica_by_its_thumbnails(self):
        path = self.write('dot.png', Image.new('RGB', (1, 1), (1, 2, 3)))
        with open(path, 'rb') as f:
            data = f.read()
        tree = mock.Mock(spec=['thumbnail'])
        tree.thumbnail.return_value = data
        self.assertEqual(images.of_replica(tree)('x.jpg', 10, 20), '1 1 010203')
        tree.thumbnail.assert_called_once_with('x.jpg', 20)
        tree.thumbnail.return_value = None
        self.assertIsNone(images.of_replica(tree)('x.jpg', 10, 20))

    def test_without_pillow_there_are_none(self):
        with mock.patch.object(images, 'Image', None):
            self.assertIsNone(images.of_replica(mock.Mock()))
            path = self.write('dot.png', Image.new('RGB', (1, 1)))
            self.assertIsNone(images.of_local_file(path, 10, 10))

if __name__ == '__main__':
    unittest.main()
