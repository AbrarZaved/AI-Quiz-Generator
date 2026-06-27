# Book data layout

The AI pipeline (`quizzes/ai/pipeline.py`) reads each book's table-of-contents
JSON, content JSON, and extracted images from this folder. The folder is
resolved from the `BOOK_DATA_DIR` env var (default: this `book_data/` folder).

Place your two books' files **exactly** like this:

```
book_data/
├── volume1/
│   ├── content_offset.json                       <- TOC (chapters + topics + page)
│   ├── volume1_final_metadata_fixed_images.json  <- page content (text + images)
│   └── v1images/                                  <- extracted page images (.jpg/.png)
│       ├── img_0001.jpg
│       └── ...
└── volume2/
    ├── content_offset.json                        <- TOC
    ├── merged_mapped_content_volume 2.json        <- page content (NOTE the space in the name)
    └── v2images/                                   <- extracted page images
        ├── img_0001.jpg
        └── ...
```

Notes:
- The `book_name` you send when creating a quiz must be `volume1` or `volume2`
  (these are the keys in `BOOK_CONFIG` inside `pipeline.py`).
- The TOC JSON must be a list of chapters shaped like:
  `[{"chapter": "...", "topics": [{"topic": "...", "page": 12}, ...]}, ...]`
- The content JSON must be a list of items shaped like:
  `[{"page_idx": 12, "type": "text", "text": "..."}, {"page_idx": 12, "type": "image", "img_path": ".../img_0001.jpg"}, ...]`
- To add more books, add another key to `BOOK_CONFIG` in `pipeline.py` and a
  matching sub-folder here.
