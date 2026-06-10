import pandas as pd

# 1. Load both CSV files
# Replace these filenames with your actual file names
df1 = pd.read_csv('articale_log_expert_classified.csv') # Has: Time, Source, Title, Content, Exact Input, Predicted Score
df2 = pd.read_csv('trainV2.csv')                           # Has: Title, Content, Title_score, Content_score

print(f"Loaded DataFrame 1 with {len(df1)} rows.")
print(f"Loaded DataFrame 2 with {len(df2)} rows.")

# 2. Rename the score column in df2 so it matches df1 perfectly
df1 = df1.rename(columns={'Predicted Score': 'Content_score'})

# 3. Select ONLY the columns that matter for your model training
# (The model only needs the text and the score)
essential_columns = ['Title', 'Content', 'Content_score']

df1_clean = df1[essential_columns].copy()
df2_clean = df2[essential_columns].copy()

# 4. Combine (concatenate) them one on top of the other
combined_df = pd.concat([df1_clean, df2_clean], ignore_index=True)

# 5. Drop any rows where the Title, Content, or Score might be missing
combined_df = combined_df.dropna(subset=essential_columns)

print(f"Successfully combined! The new dataset has {len(combined_df)} rows.")

# 6. Save the unified dataset to a new CSV file
output_filename = 'final_training_data.csv'
combined_df.to_csv(output_filename, index=False, encoding='utf-8-sig')

print(f"Saved combined data to: {output_filename}")