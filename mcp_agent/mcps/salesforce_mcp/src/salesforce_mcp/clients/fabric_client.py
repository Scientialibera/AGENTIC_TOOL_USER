"""
Microsoft Fabric lakehouse client for retrieving document content.

This client handles connections to Microsoft Fabric lakehouse to retrieve
document text content that has been processed by the data engineering team.
"""

import structlog
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import pyodbc
import httpx
from azure.identity import DefaultAzureCredential

logger = structlog.get_logger(__name__)


class FabricLakehouseClient:
    """Client for Microsoft Fabric lakehouse operations."""
    
    def __init__(
        self,
        lakehouse_sql_endpoint: str,
        lakehouse_database: str,
        lakehouse_workspace_id: Optional[str] = None,
        connection_timeout: int = 30,
        dev_mode: bool = False
    ):
        """
        Initialize the Fabric lakehouse client.
        
        Args:
            lakehouse_sql_endpoint: SQL endpoint for the lakehouse
            lakehouse_database: Database name in the lakehouse
            lakehouse_workspace_id: Optional workspace ID for REST API calls
            connection_timeout: Connection timeout in seconds
            dev_mode: If True, returns dummy data instead of connecting to real lakehouse
        """
        self.lakehouse_sql_endpoint = lakehouse_sql_endpoint
        self.lakehouse_database = lakehouse_database
        self.lakehouse_workspace_id = lakehouse_workspace_id
        self.connection_timeout = connection_timeout
        self.dev_mode = dev_mode
        
        if not self.dev_mode:
            self.credential = DefaultAzureCredential()
            # Build SQL connection string using Azure AD authentication
            self.connection_string = self._build_connection_string()
        else:
            logger.info("Fabric client running in dev mode - using dummy data")
    
    def _get_dummy_document_data(self) -> List[Dict[str, Any]]:
        """Generate dummy document data for sales planning context."""
        return [
            {
                "file_id": "doc_salesforce_account_plan",
                "account_id": "acc_salesforce",
                "file_name": "Salesforce_Account_Plan_2024.pdf",
                "file_text": "Salesforce Account Plan 2024. Current Status: Active Enterprise customer with $2.5M annual contract. Key contacts: CEO Marc Benioff, CTO Parker Harris. Current solutions: Sales Cloud Enterprise, Service Cloud, Marketing Cloud. Expansion opportunities: Einstein Sales, MuleSoft integration, Slack integration. Renewal due: March 15, 2025. Risk factors: AWS hosting costs increasing, considering Microsoft migration. Upsell potential: $500K in additional licenses.",
                "file_summary": "Salesforce account plan showing $2.5M enterprise customer with expansion opportunities in Einstein Sales and integrations.",
                "sharepoint_url": "https://company.sharepoint.com/accounts/Salesforce_Account_Plan_2024.pdf",
                "last_modified": datetime.now(),
                "content_type": "application/pdf",
                "file_size": 245760
            },
            {
                "file_id": "doc_microsoft_opportunity", 
                "account_id": "acc_microsoft",
                "file_name": "Microsoft_Cloud_Opportunity_Assessment.pdf",
                "file_text": "Microsoft Cloud Opportunity Assessment. Prospect Status: High-priority enterprise target with 221K employees and $245B revenue. Current technology stack: Legacy on-premises systems, minimal cloud adoption. Opportunity: $50M+ Azure migration project, Teams collaboration, Office 365 enterprise agreement. Key decision makers: CEO Satya Nadella, EVP Scott Guthrie. Competition: AWS currently preferred vendor. Timeline: 18-month sales cycle. Success factors: Demonstrate Azure cost savings vs AWS, provide migration expertise.",
                "file_summary": "Microsoft cloud opportunity assessment for $50M+ Azure migration and Office 365 enterprise deal.",
                "sharepoint_url": "https://company.sharepoint.com/opportunities/Microsoft_Cloud_Opportunity_Assessment.pdf",
                "last_modified": datetime.now(),
                "content_type": "application/pdf", 
                "file_size": 342150
            },
            {
                "file_id": "doc_oracle_renewal_strategy",
                "account_id": "acc_oracle",
                "file_name": "Oracle_Database_Renewal_Strategy.pdf",
                "file_text": "Oracle Database Renewal Strategy. Current Status: Active customer with $1.8M annual support contract expiring November 30, 2024. Database versions: Oracle 19c Enterprise Edition. Key contacts: CEO Safra Catz, EVP Juan Loaiza. Current pain points: High licensing costs, complex upgrade path. Alternatives considered: AWS RDS, Azure Database, PostgreSQL migration. Retention strategy: Offer Oracle Cloud migration incentives, negotiate 20% discount on renewal. Risk: Customer evaluating open-source alternatives.",
                "file_summary": "Oracle database renewal strategy for $1.8M support contract with focus on cloud migration incentives.",
                "sharepoint_url": "https://company.sharepoint.com/renewals/Oracle_Database_Renewal_Strategy.pdf",
                "last_modified": datetime.now(),
                "content_type": "application/pdf",
                "file_size": 189440
            },
            {
                "file_id": "doc_sap_prospect_analysis",
                "account_id": "acc_sap",
                "file_name": "SAP_SE_Prospect_Analysis.pdf",
                "file_text": "SAP SE Prospect Analysis. Target Profile: European enterprise software leader with 111K employees and $33.8B revenue. Current ERP: Legacy SAP ECC 6.0. Opportunity: S/4HANA migration project valued at $25M. Key decision makers: CEO Christian Klein, COO Luka Mucic. Competition: Oracle ERP Cloud, Microsoft Dynamics. Entry strategy: Partner with existing Salesforce integration, demonstrate ROI through digital transformation. Timeline: 24-month evaluation process.",
                "file_summary": "SAP prospect analysis for $25M S/4HANA migration opportunity with Salesforce integration angle.",
                "sharepoint_url": "https://company.sharepoint.com/prospects/SAP_SE_Prospect_Analysis.pdf",
                "last_modified": datetime.now(),
                "content_type": "application/pdf",
                "file_size": 298000
            }
        ]
    
    def _build_connection_string(self) -> str:
        """Build connection string for lakehouse SQL endpoint."""
        return (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={self.lakehouse_sql_endpoint};"
            f"DATABASE={self.lakehouse_database};"
            f"Authentication=ActiveDirectoryMsi;"
            f"Connection Timeout={self.connection_timeout};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
        )
    
    async def get_document_content(
        self,
        document_id: str,
        account_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve document content from the lakehouse.
        
        Args:
            document_id: Document ID to retrieve
            account_id: Optional account ID for filtering
            
        Returns:
            Dictionary with document content and metadata
        """
        # Return dummy data in dev mode
        if self.dev_mode:
            dummy_docs = self._get_dummy_document_data()
            for doc in dummy_docs:
                if doc["file_id"] == document_id:
                    if account_id is None or doc["account_id"] == account_id:
                        logger.info(f"Returning dummy document data for {document_id}")
                        return doc
            logger.info(f"No dummy document found for {document_id}")
            return None
        
        try:
            query = """
            SELECT 
                file_id,
                account_id,
                file_name,
                file_text,
                file_summary,
                sharepoint_url,
                last_modified,
                content_type,
                file_size
            FROM contracts_text 
            WHERE file_id = ?
            """
            
            params = [document_id]
            
            # Add account filter if provided
            if account_id:
                query += " AND account_id = ?"
                params.append(account_id)
            
            result = await self._execute_query(query, params)
            
            if result:
                return {
                    "file_id": result[0]["file_id"],
                    "account_id": result[0]["account_id"],
                    "file_name": result[0]["file_name"],
                    "file_text": result[0]["file_text"],
                    "file_summary": result[0]["file_summary"],
                    "sharepoint_url": result[0]["sharepoint_url"],
                    "last_modified": result[0]["last_modified"],
                    "content_type": result[0]["content_type"],
                    "file_size": result[0]["file_size"]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get document content for {document_id}: {e}")
            return None
    
    async def get_documents_by_ids(
        self,
        document_ids: List[str],
        account_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve multiple documents by their IDs.
        
        Args:
            document_ids: List of document IDs to retrieve
            account_id: Optional account ID for filtering
            
        Returns:
            List of document dictionaries
        """
        # Return dummy data in dev mode
        if self.dev_mode:
            dummy_docs = self._get_dummy_document_data()
            matched_docs = []
            for doc_id in document_ids:
                for doc in dummy_docs:
                    if doc["file_id"] == doc_id:
                        if account_id is None or doc["account_id"] == account_id:
                            matched_docs.append(doc)
                            break
            logger.info(f"Returning {len(matched_docs)} dummy documents")
            return matched_docs
        
        try:
            if not document_ids:
                return []
            
            # Create parameter placeholders for the IN clause
            placeholders = ",".join("?" * len(document_ids))
            
            query = f"""
            SELECT 
                file_id,
                account_id,
                file_name,
                file_text,
                file_summary,
                sharepoint_url,
                last_modified,
                content_type,
                file_size
            FROM contracts_text 
            WHERE file_id IN ({placeholders})
            """
            
            params = document_ids.copy()
            
            # Add account filter if provided
            if account_id:
                query += " AND account_id = ?"
                params.append(account_id)
            
            results = await self._execute_query(query, params)
            
            documents = []
            for row in results:
                documents.append({
                    "file_id": row["file_id"],
                    "account_id": row["account_id"],
                    "file_name": row["file_name"],
                    "file_text": row["file_text"],
                    "file_summary": row["file_summary"],
                    "sharepoint_url": row["sharepoint_url"],
                    "last_modified": row["last_modified"],
                    "content_type": row["content_type"],
                    "file_size": row["file_size"]
                })
            
            return documents
            
        except Exception as e:
            logger.error(f"Failed to get documents by IDs: {e}")
            return []
    
    async def get_account_documents(
        self,
        account_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all documents for a specific account.
        
        Args:
            account_id: Account ID to get documents for
            limit: Maximum number of documents to return
            
        Returns:
            List of document dictionaries
        """
        try:
            query = """
            SELECT TOP (?)
                file_id,
                account_id,
                file_name,
                file_text,
                file_summary,
                sharepoint_url,
                last_modified,
                content_type,
                file_size
            FROM contracts_text 
            WHERE account_id = ?
            ORDER BY last_modified DESC
            """
            
            results = await self._execute_query(query, [limit, account_id])
            
            documents = []
            for row in results:
                documents.append({
                    "file_id": row["file_id"],
                    "account_id": row["account_id"],
                    "file_name": row["file_name"],
                    "file_text": row["file_text"],
                    "file_summary": row["file_summary"],
                    "sharepoint_url": row["sharepoint_url"],
                    "last_modified": row["last_modified"],
                    "content_type": row["content_type"],
                    "file_size": row["file_size"]
                })
            
            return documents
            
        except Exception as e:
            logger.error(f"Failed to get documents for account {account_id}: {e}")
            return []
    
    async def search_documents(
        self,
        search_text: str,
        account_id: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search documents by text content.
        
        Args:
            search_text: Text to search for in document content
            account_id: Optional account ID for filtering
            limit: Maximum number of results to return
            
        Returns:
            List of matching document dictionaries
        """
        try:
            base_query = """
            SELECT TOP (?)
                file_id,
                account_id,
                file_name,
                file_text,
                file_summary,
                sharepoint_url,
                last_modified,
                content_type,
                file_size
            FROM contracts_text 
            WHERE (
                CONTAINS(file_text, ?) 
                OR CONTAINS(file_name, ?)
                OR CONTAINS(file_summary, ?)
            )
            """
            
            params = [limit, search_text, search_text, search_text]
            
            if account_id:
                base_query += " AND account_id = ?"
                params.append(account_id)
            
            base_query += " ORDER BY last_modified DESC"
            
            results = await self._execute_query(base_query, params)
            
            documents = []
            for row in results:
                documents.append({
                    "file_id": row["file_id"],
                    "account_id": row["account_id"],
                    "file_name": row["file_name"],
                    "file_text": row["file_text"],
                    "file_summary": row["file_summary"],
                    "sharepoint_url": row["sharepoint_url"],
                    "last_modified": row["last_modified"],
                    "content_type": row["content_type"],
                    "file_size": row["file_size"]
                })
            
            return documents
            
        except Exception as e:
            logger.error(f"Failed to search documents: {e}")
            return []
    
    async def get_document_chunks(
        self,
        document_id: str,
        chunk_size: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Get document content split into chunks.
        
        Args:
            document_id: Document ID to chunk
            chunk_size: Size of each chunk in characters
            
        Returns:
            List of document chunks with metadata
        """
        try:
            document = await self.get_document_content(document_id)
            
            if not document or not document.get("file_text"):
                return []
            
            text = document["file_text"]
            chunks = []
            
            for i in range(0, len(text), chunk_size):
                chunk_text = text[i:i + chunk_size]
                chunks.append({
                    "file_id": document["file_id"],
                    "chunk_index": i // chunk_size,
                    "chunk_text": chunk_text,
                    "chunk_start": i,
                    "chunk_end": min(i + chunk_size, len(text)),
                    "file_name": document["file_name"],
                    "account_id": document["account_id"],
                    "sharepoint_url": document["sharepoint_url"]
                })
            
            return chunks
            
        except Exception as e:
            logger.error(f"Failed to get document chunks for {document_id}: {e}")
            return []
    
    async def _execute_query(
        self,
        query: str,
        params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL query against the lakehouse.
        
        Args:
            query: SQL query to execute
            params: Optional query parameters
            
        Returns:
            List of result dictionaries
        """
        try:
            with pyodbc.connect(self.connection_string) as connection:
                with connection.cursor() as cursor:
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)
                    
                    # Get column names
                    columns = [desc[0] for desc in cursor.description] if cursor.description else []
                    
                    # Fetch all rows
                    rows = cursor.fetchall()
                    
                    # Convert to list of dictionaries
                    results = []
                    for row in rows:
                        row_dict = {columns[i]: row[i] for i in range(len(columns))}
                        results.append(row_dict)
                    
                    return results
                    
        except Exception as e:
            logger.error(f"Failed to execute query: {e}")
            raise
    
    async def test_connection(self) -> bool:
        """
        Test the connection to the lakehouse.
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            result = await self._execute_query("SELECT 1 as test_value")
            return len(result) > 0 and result[0]["test_value"] == 1
            
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    async def get_table_info(self, table_name: str = "contracts_text") -> Dict[str, Any]:
        """
        Get information about a table in the lakehouse.
        
        Args:
            table_name: Name of the table to inspect
            
        Returns:
            Dictionary with table information
        """
        try:
            # Get column information
            columns_query = """
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
            """
            
            columns = await self._execute_query(columns_query, [table_name])
            
            # Get row count
            count_query = f"SELECT COUNT(*) as row_count FROM {table_name}"
            count_result = await self._execute_query(count_query)
            row_count = count_result[0]["row_count"] if count_result else 0
            
            return {
                "table_name": table_name,
                "columns": columns,
                "row_count": row_count
            }
            
        except Exception as e:
            logger.error(f"Failed to get table info for {table_name}: {e}")
            return {"table_name": table_name, "columns": [], "row_count": 0}
    
    async def close(self):
        """Close the client and clean up resources."""
        # No specific cleanup needed for ODBC connections as they auto-close
        logger.info("Fabric lakehouse client closed")