import pandas as pd


def change_name(df):
    df['Source'] = df['Source'].replace('13tv', 'Channel 13')
    df['Source'] = df['Source'].replace('Mako', 'Channel 12')
    df['Source'] = df['Source'].replace('i24NEWS', 'I24 NEWS')
    df['Source'] = df['Source'].replace('I24', 'I24 NEWS')
    df['Source'] = df['Source'].replace('I24news', 'I24 NEWS')

    df.to_csv('log_csv.csv', index=False, encoding='utf-8')
    print("success")


def remove_title_duplicates(df):
    df.drop_duplicates(subset=['Title'], keep='first', inplace=True)
    df.to_csv('log_csv.csv', index=False, encoding='utf-8-sig')

    print("Duplicates removed successfully")

def table_fix(table_name):
    df = pd.read_csv(f'{table_name}.csv', encoding='utf-8-sig', header=0)
    df.to_csv(f'{table_name}.csv', index=False, encoding='utf-8-sig')

if __name__ == '__main__':
    df = pd.read_csv('log_csv.csv')
    remove_title_duplicates(df)


