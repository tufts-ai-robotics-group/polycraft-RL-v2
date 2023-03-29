
def get_hinted_items(all_objects, hints, split_words=False):
    hinted_items = []
    hints = str(hints)
    for obj in all_objects:
        if split_words:
            obj_components = obj.split("_")
        else:
            obj_components = [obj]
        for component in obj_components:
            if component in hints:
                hinted_items.append(obj)
                break
    return hinted_items