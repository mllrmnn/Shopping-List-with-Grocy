"""Tests for utils module."""

from custom_components.shopping_list_with_grocy_polling.utils import convert_word_to_number


class TestConvertWordToNumber:
    """Tests for convert_word_to_number."""

    # â”€â”€ Numeric strings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_integer_string(self):
        assert convert_word_to_number("3") == 3

    def test_integer_string_with_spaces(self):
        assert convert_word_to_number("  2  ") == 2

    def test_zero(self):
        assert convert_word_to_number("0") == 0

    # â”€â”€ French â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_french_un(self):
        assert convert_word_to_number("un") == 1

    def test_french_une(self):
        assert convert_word_to_number("une") == 1

    def test_french_deux(self):
        assert convert_word_to_number("deux") == 2

    def test_french_trois(self):
        assert convert_word_to_number("trois") == 3

    def test_french_cinq(self):
        assert convert_word_to_number("cinq") == 5

    def test_french_dix(self):
        assert convert_word_to_number("dix") == 10

    def test_french_ordinal_premier(self):
        assert convert_word_to_number("premier") == 1

    def test_french_ordinal_deuxieme(self):
        assert convert_word_to_number("deuxiÃ¨me") == 2

    # â”€â”€ English â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_english_one(self):
        assert convert_word_to_number("one") == 1

    def test_english_two(self):
        assert convert_word_to_number("two") == 2

    def test_english_five(self):
        assert convert_word_to_number("five") == 5

    def test_english_ten(self):
        assert convert_word_to_number("ten") == 10

    def test_english_ordinal_first(self):
        assert convert_word_to_number("first") == 1

    def test_english_ordinal_third(self):
        assert convert_word_to_number("third") == 3

    # â”€â”€ Spanish â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_spanish_uno(self):
        assert convert_word_to_number("uno") == 1

    def test_spanish_tres(self):
        assert convert_word_to_number("tres") == 3

    def test_spanish_cinco(self):
        assert convert_word_to_number("cinco") == 5

    # â”€â”€ German â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_german_zwei(self):
        assert convert_word_to_number("zwei") == 2

    def test_german_funf(self):
        assert convert_word_to_number("fÃ¼nf") == 5

    def test_german_zehn(self):
        assert convert_word_to_number("zehn") == 10

    # â”€â”€ Phrase with embedded number word â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_phrase_choice_two(self):
        assert convert_word_to_number("choice two") == 2

    def test_phrase_numero_trois(self):
        assert convert_word_to_number("numÃ©ro trois") == 3

    # â”€â”€ Digit embedded in a string â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_string_with_trailing_digit(self):
        assert convert_word_to_number("option3") == 3

    # â”€â”€ Edge cases â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_empty_string(self):
        assert convert_word_to_number("") is None

    def test_none_input(self):
        assert convert_word_to_number(None) is None

    def test_unknown_word(self):
        assert convert_word_to_number("blorp") is None

    def test_uppercase(self):
        assert convert_word_to_number("DEUX") == 2

    def test_mixed_case(self):
        assert convert_word_to_number("Trois") == 3
