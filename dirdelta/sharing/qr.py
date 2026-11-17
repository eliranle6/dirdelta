"""A QR code drawn in the terminal (lines()), to scan from the screen with a phone's camera: in half
blocks, two of its rows a line, so it's about square"""
import segno

# Black on bright white, whatever the terminal's colors: a scanner wants dark on light, and the
# light quiet zone around it
_STYLE = '\033[30;107m'
_RESET = '\033[0m'
# The light modules around it: the standard's 4 would make it taller than a small terminal, and 2
# scans fine from a screen
BORDER = 2
# By whether the upper and the lower module of a line's character are dark
_HALF_BLOCKS = {(False, False): ' ', (True, False): '▀', (False, True): '▄', (True, True): '█'}


def lines(text):
    """text as a QR code (medium error correction), in lines to print as they are, each as wide as
    the code and its border"""
    rows = [[bool(module) for module in row]
            for row in segno.make(text, error='m', micro=False).matrix_iter(scale=1, border=BORDER)]
    if len(rows) % 2:
        rows.append([False] * len(rows[0]))
    return [_STYLE + ''.join(_HALF_BLOCKS[pair] for pair in zip(upper, lower)) + _RESET
            for upper, lower in zip(rows[::2], rows[1::2])]
