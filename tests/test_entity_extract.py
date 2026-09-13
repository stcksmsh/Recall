from src.consolidate.entity_extract import extract_entity


def test_no_identifier_like_tokens_stays_unsorted():
    result = extract_entity("Decided to keep the meeting short and revisit next week.")
    assert result.entity == "unsorted"
    assert result.ambiguous is False
    assert result.candidates == []


def test_single_snake_case_candidate_is_unambiguous():
    result = extract_entity("the_database now uses SQLite instead of the old flat files.")
    assert result.entity == "thedatabase"
    assert result.ambiguous is False


def test_backtick_quoted_candidate_is_picked_up():
    result = extract_entity("Renamed `hybrid.py`'s ranking function for clarity.")
    assert result.entity == "hybrid.py"
    assert result.ambiguous is False


def test_most_frequent_candidate_wins_over_a_passing_mention():
    content = (
        "the_database migration finished; the_database now stores JSON blobs. "
        "Briefly considered other_service but decided against it."
    )
    result = extract_entity(content)
    assert result.entity == "thedatabase"
    assert result.ambiguous is False


def test_tied_frequency_candidates_are_ambiguous():
    result = extract_entity("Compared the_database against other_service and picked neither yet.")
    assert result.ambiguous is True
    assert result.entity == "unsorted"
    assert set(result.candidates) == {"thedatabase", "otherservice"}


def test_snake_case_and_camel_case_spellings_fold_to_the_same_entity():
    """Regression: two INDEPENDENTLY extracted captures, one using the snake_case spelling of a
    name and the other the CamelCase spelling, must resolve to the identical entity string --
    otherwise by_entity_or_scope(entity=X) can never find both, defeating the fold."""
    snake = extract_entity("session_start.py reads brain/semantic/facts/ directly, no index build.")
    camel = extract_entity("Both AIW and Recall install independent SessionStart hooks.")
    assert snake.entity == camel.entity
    assert snake.entity == "sessionstart"
    assert snake.ambiguous is False
    assert camel.ambiguous is False
