from ocr_service.infrastructure.ocr.paddle_engine import PaddleOCREngine, _reading_order


def test_reading_order_is_top_to_bottom_then_left_to_right() -> None:
    entries = [
        ([[100, 100], [200, 100], [200, 120], [100, 120]], "second", 0.9),
        ([[10, 100], [90, 100], [90, 120], [10, 120]], "first", 0.9),
        ([[10, 160], [90, 160], [90, 180], [10, 180]], "third", 0.9),
    ]
    assert [item[1] for item in _reading_order(entries)] == ["first", "second", "third"]


def test_paddle_v3_mapping_retains_text_boxes_and_confidence() -> None:
    output = [
        {
            "res": {
                "dt_polys": [[[1, 2], [30, 2], [30, 12], [1, 12]]],
                "rec_texts": ["Bonjour"],
                "rec_scores": [0.94],
            }
        }
    ]
    assert PaddleOCREngine._parse_v3_output(output) == [
        ([[1.0, 2.0], [30.0, 2.0], [30.0, 12.0], [1.0, 12.0]], "Bonjour", 0.94)
    ]
