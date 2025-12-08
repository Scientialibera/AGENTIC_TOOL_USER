# cli_sql_test_fixed.py

import struct
import pyodbc
from azure.identity import DefaultAzureCredential

SERVER = "testserverarbela.database.windows.net"
DATABASE = "testtexttosql"

SQL_COPT_SS_ACCESS_TOKEN = 1256
TOKEN_SCOPE = "https://database.windows.net/.default"

conn_str = (
    "Driver={ODBC Driver 18 for SQL Server};"
    f"Server=tcp:{SERVER},1433;"
    f"Database={DATABASE};"
    "Encrypt=yes;"
    "TrustServerCertificate=no;"
    "Connection Timeout=30;"
)

print("Connection string:", conn_str)

# 1) Get token with DefaultAzureCredential (respects az login / VS Code login etc.)
cred = DefaultAzureCredential()
token = cred.get_token(TOKEN_SCOPE).token   # string

# 2) Build the ACCESSTOKEN struct EXACTLY how the driver expects it:
token_bytes = token.encode("utf-16-le")     # UTF-16-LE is critical
token_struct = struct.pack("<I", len(token_bytes)) + token_bytes

print("Token length (bytes):", len(token_bytes))

# 3) Connect, passing token_struct as pre-attribute 1256
conn = pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})
cur = conn.cursor()

cur.execute("SELECT TOP 1 name FROM sys.tables")
row = cur.fetchone()
print("First table:", row)

cur.close()
conn.close()
print("OK")
