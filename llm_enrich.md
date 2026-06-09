 Both files are ready. To run:

  1. Set your OpenRouter key in llm_config.py → API_KEY
  2. python llm_enrich.py

  What's in the config (llm_config.py):
  - MODEL / BASE_URL / API_KEY
  - BATCH_SIZE (20), CONCURRENCY (5), TEMPERATURE (0.1)
  - COLUMNS — maps bundle fields to your actual CSV column names; change these if your column names differ
  - INSUFFICIENT_DATA — the sentinel string written when input is too sparse
  - SYSTEM_PROMPT, BATCH_USER_TEMPLATE, SINGLE_USER_TEMPLATE — all editable

  What the script does with low-quality inputs: the LLM is explicitly instructed to output INSUFFICIENT_DATA as the text value (not a failure state, just a       
  - BATCH_SIZE (20), CONCURRENCY (5), TEMPERATURE (0.1)
  - COLUMNS — maps bundle fields to your actual CSV column names; change these if your column names differ
  - INSUFFICIENT_DATA — the sentinel string written when input is too sparse
  - SYSTEM_PROMPT, BATCH_USER_TEMPLATE, SINGLE_USER_TEMPLATE — all editable

  What the script does with low-quality inputs: the LLM is explicitly instructed to output INSUFFICIENT_DATA as the text value (not a failure state, just 
  a string). Rows where every bundle field is empty will reliably trigger it. After the run, trustpilot_embeddings.csv can be filtered with
  df[df['embedding_text'] != 'INSUFFICIENT_DATA'] before embedding.

✻ Brewed for 3m 54s

※ recap: Building a Trustpilot company dataset for embedding-based clustering. Four scripts are complete: category scraper, description enricher, homepage
   meta fetcher, and LLM text synthesizer. Next action: set your OpenRouter API key in llm_config.py and run the scripts in sequence.