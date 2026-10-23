from dirdelta import picker


def run_menu(actions):
    """Show a menu of (label, handler) pairs and call the chosen label's handler, if it has one.

    Returns the chosen label, or None if the user quit the menu.
    """
    label = picker.pick_option([label for label, _ in actions])
    handler = next((handler for _label, handler in actions if _label == label), None)
    if handler is not None:
        handler()
    return label
