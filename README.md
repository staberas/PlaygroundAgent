# PlaygroundAgent

## Unsplash CSV image rewriter

`unsplash_csv_rewriter.py` reads a CSV file, looks at the `Image` column, extracts keywords from the old Unsplash URL query string (text after `?`), fetches a relevant image from Unsplash, randomly selects from search results, and replaces the column with a new 800x600 image URL.

### Usage

```bash
python3 unsplash_csv_rewriter.py input.csv output.csv
```

Optional flags:

- `--image-column Image` (default is `Image`)
- `--access-key ...` (defaults to `UNSPLASH_ACCESS_KEY` env var or embedded key)
- `--secret ...` and `--app-id ...` are accepted for completeness but not required by this flow

### Example

```bash
python3 unsplash_csv_rewriter.py products.csv products.updated.csv --image-column Image
```
