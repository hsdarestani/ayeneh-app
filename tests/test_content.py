from app.content import TRAITS


def test_traits_are_unique_and_complete():
    assert len(TRAITS) == 8
    assert len({trait.key for trait in TRAITS}) == len(TRAITS)
    assert all(trait.self_question and trait.other_question for trait in TRAITS)
