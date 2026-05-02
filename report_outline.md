# Dàn ý Báo cáo: Hệ thống Semantic Recruitment Matcher
*(Dựa trên mã nguồn thực tế: FastAPI, PostgreSQL, Milvus)*

## 1. Giới thiệu (Introduction)
- **Bối cảnh bài toán:** Điểm yếu của tuyển dụng truyền thống (keyword matching) và giải pháp Semantic Matching (hiểu ngữ nghĩa).
- **Mục tiêu đề tài:** Xây dựng hệ thống so khớp thông minh giữa Job Descriptions (JDs) và Candidate Profiles (CVs).
- **Phạm vi:** 
  - Tập trung vào lĩnh vực IT/Tech.
  - Sử dụng mô hình đa ngôn ngữ (Multilingual Sentence Transformer), sẵn sàng mở rộng cho dữ liệu tiếng Việt trong tương lai dù dataset hiện tại là tiếng Anh.

## 2. Cơ sở lý thuyết (Theoretical Background)
- **Vector Embeddings:** Nguyên lý chuyển hóa văn bản thành mảng số thực (float vectors) qua mô hình Sentence-Transformers.
- **Độ đo khoảng cách (Distance Metrics):** Giải thích Cosine Similarity dùng trong chấm điểm mức độ liên quan.
- **Keyword Search vs. Semantic Search:** So sánh trực diện và đưa ra lý do kết hợp cả hai phương pháp (Hybrid Search).

## 3. Thiết kế hệ thống (System Design)
- **Kiến trúc tổng thể:** 
  - Backend: FastAPI.
  - Database: PostgreSQL (lưu trữ metadata) và Milvus (lưu trữ và tìm kiếm vector).
- **Chiến lược làm sạch dữ liệu (Data Cleaning & Handling Missing Data):**
  - Xử lý các cột bị khuyết thiếu lớn như `Looking For` (61.2%) và `Highlights` (58.2%).
  - Chiến thuật ghép nối chuỗi `cv_text` + `position` an toàn cho embedding.
- **Pipelines:**
  - Data Pipeline: HuggingFace Datasets → PostgreSQL (thực thi qua `Postgre_config.py`).
  - Embedding Pipeline: Text → `paraphrase-multilingual-MiniLM-L12-v2` → Milvus Collections (`datasets_v2.ipynb`).
- **Sơ đồ luồng dữ liệu (Data Flow Diagram):** Mô tả cách dữ liệu đi từ Input Query đến khi trả về Results.

## 4. Cài đặt & Thực nghiệm (Implementation)
- **Cấu hình & Kết nối cơ sở dữ liệu:** Đọc `config.properties`, khởi tạo kết nối `psycopg2` với PostgreSQL và cấu hình Milvus.
- **Cấu trúc FastAPI Endpoints:** Quản lý `/api/search`, `/api/cvs`, `/api/stats`, `/api/suggest`.
- **Triển khai thuật toán SQL Search (Custom Keyword-based Weighted Scoring):**
  - Trích xuất từ khóa (Keyword Extraction & Stop words removal).
  - Sử dụng toán tử `ILIKE` để không phân biệt chữ hoa/thường.
  - Tính điểm cộng dồn (Weighted Scoring) ưu tiên theo các cột `position`, `keyword`, `cv_text`, `highlights`.
  - Chiến lược nới lỏng tìm kiếm (Search Tuning: AND -> PARTIAL -> OR) để tối ưu hiệu suất.
- **Triển khai thuật toán Vector Search (Hybrid Re-ranking):**
  - Quét Cosine Similarity bằng Milvus.
  - Kỹ thuật **Batch SQL Fetching**: Lấy id từ Milvus và query ngược PostgreSQL bằng một lệnh `IN (...)` duy nhất để tránh nghẽn cổ chai.
  - Kỹ thuật **Lexical Bonus**: Chấm điểm Hybrid bằng cách cộng thêm điểm ngữ vựng vào điểm Cosine gốc (0.15 cho Position, 0.1 cho Keyword...).

## 5. Demo & Kết quả (Results)
- **Giao diện trực quan:** Minh họa kết quả tìm kiếm chia thành 2 cột so sánh trực tiếp SQL vs Milvus.
- **Phân tích 5 câu query mẫu:** (Ví dụ: "Python backend developer", "strong communicator...").
- **Phân tích điểm số:** 
  - Tại sao Milvus trả về điểm Cosine từ 0.2 - 0.53 là hợp lý (do sự khác biệt về cấu trúc giữa câu ngắn JD và đoạn văn dài CV).

## 6. Đánh giá & Thảo luận (Discussion)
- **Ưu / Nhược điểm:** Của thuật toán SQL có trọng số so với Hybrid Vector Search.
- **Hạn chế của hệ thống:**
  - Không có ground-truth JD-CV pairs để đánh giá độ chính xác (Precision/Recall).
  - Dataset của JDs và CVs được thu thập từ các nguồn độc lập.
- **Hướng phát triển tương lai (Future Works):**
  - Cải tiến metadata filtering trước khi search Vector.
  - Nâng cấp mô hình embedding (VD: `all-mpnet-base-v2` hoặc BGE).
  - Thử nghiệm các kiến trúc đa phương thức (Multimodal) như CLIP để đánh giá thêm hình ảnh/portfolio.

## 7. Kết luận (Conclusion)
- Tóm tắt các kết quả đạt được (hệ thống chạy mượt, hybrid search phát huy sức mạnh).
- Bài học rút ra về việc kết hợp cơ sở dữ liệu truyền thống (PostgreSQL) và Vector Database (Milvus) cho các ứng dụng AI thực tế.
