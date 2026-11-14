"""Companion names as speech-to-text writes them (red/companions.py match_name, switch_target)."""

import pytest

from red import companions


@pytest.mark.parametrize("heard, who", [
    ("Remy", "remy"), ("Remmy", "remy"), ("Remi", "remy"), ("Rémy", "remy"), ("Rennel", "remy"),
    ("Rami", "remy"), ("Ramy", "remy"), ("Reemy", "remy"), ("Remy's", "remy"), ("hey Remmy", "remy"),
    ("Asha", "asha"), ("Usha", "asha"), ("Asia", "asha"), ("Aysha", "asha"), ("Ayesha", "asha"),
    ("Aisha", "asha"), ("Aasha", "asha"), ("Esha", "asha"), ("okay, Asha please", "asha"),
    ("Bruno", "bruno"), ("Bruna", "bruno"), ("Brunno", "bruno"), ("Burno", "bruno"),
    ("Winston", "winston"), ("Winsten", "winston"), ("Winstone", "winston"), ("win ston", "winston"),
    ("Red", "red"), ("Redd", "red"), ("hey red", "red"),
])
def test_names_heard_wrong_still_match(heard, who, tmp_path):
    assert companions.match_name(heard, tmp_path) == who


@pytest.mark.parametrize("heard", [
    "my mom", "mom", "mum", "dad", "Fred", "bed", "read me", "remind", "remember", "ready", "really",
    "rainy", "Rome", "remix", "Rachel", "Ash", "Asian", "Asher", "Sasha", "Russia", "Bruce", "brown",
    "brother", "windows", "window", "winter", "Wilson", "dark mode", "the music", "", "a", "me",
])
def test_other_words_are_not_names(heard, tmp_path):
    assert companions.match_name(heard, tmp_path) is None


def test_only_the_first_words_count(tmp_path):
    """A whole sentence that happens to contain a name later isn't a name."""
    assert companions.match_name("I need to remember to call Remy", tmp_path) is None


def test_strict_matching_takes_only_names_and_aliases(tmp_path):
    assert companions.match_name("Remmy", tmp_path, fuzzy=False) == "remy"     # same sound key
    assert companions.match_name("Rennel", tmp_path, fuzzy=False) == "remy"    # an alias
    assert companions.match_name("Esha", tmp_path, fuzzy=False) is None        # only near


def test_a_users_alias_is_used(tmp_path):
    folder = tmp_path / "companions" / "remy"
    folder.mkdir(parents=True)
    (folder / "companion.toml").write_text('aliases = ["remington"]\n', encoding="utf-8")
    companions._NAME_CACHE.clear()
    assert companions.match_name("Remington", tmp_path) == "remy"


@pytest.mark.parametrize("said, who", [
    ("Switch to Rennel", "remy"),                 # red.log 2026-11-13 22:47
    ("talk to Usha", "asha"), ("let me talk to Aysha", "asha"), ("bring Remmy", "remy"),
    ("bring Remy back", "remy"), ("bring in Bruno", "bruno"), ("switch to Winsten please", "winston"),
    ("go back to Red", "red"), ("put on Asha", "asha"),
])
def test_switching_hears_names_by_sound(said, who, tmp_path):
    assert companions.switch_target(said, tmp_path) == who


@pytest.mark.parametrize("said", [
    "talk to my mom", "switch to dark mode", "go to Asia", "I want to go to Asia", "bring me water",
    "get Rennel", "switch to windows", "talk to me", "be quiet",
])
def test_switching_never_takes_other_things_for_a_name(said, tmp_path):
    assert companions.switch_target(said, tmp_path) is None


def test_name_similarity_is_symmetric_enough_and_bounded():
    assert companions.name_similarity("Remmy", "Remy") == 1.0
    assert 0.0 <= companions.name_similarity("Rennel", "Remy") < companions.MIN_SIMILARITY
    assert companions.name_similarity("Fred", "Red") == 0.0
