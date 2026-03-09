from symspellpy import SymSpell

sym_spell = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)

dictionary_loaded = False


def load_dictionary(vocab):
    global dictionary_loaded

    if dictionary_loaded:
        return

    for word in vocab:
        sym_spell.create_dictionary_entry(word, 1)

    dictionary_loaded = True


def correct_sentence(text: str):

    suggestions = sym_spell.lookup_compound(
        text,
        max_edit_distance=2
    )

    if suggestions:
        return suggestions[0].term

    return text