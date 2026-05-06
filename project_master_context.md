# MASTER CONTEXT: SEMANTIC RECRUITMENT MATCHER
*Tài liệu này tổng hợp toàn bộ thông tin gốc, kiến trúc, luồng hoạt động và thuật toán của dự án. File này được thiết kế tối ưu làm "Context Prompt" cho các AI Model khác để viết Báo cáo/Đồ án.*

---

## 1. TỔNG QUAN DỰ ÁN (PROJECT OVERVIEW)
- **Tên dự án:** Semantic Recruitment Matcher
- **Mục tiêu:** Xây dựng một hệ thống tìm kiếm và so khớp ứng viên (Candidate CVs) với yêu cầu tuyển dụng (Job Descriptions) thông minh, vượt qua giới hạn của tìm kiếm từ khóa truyền thống (Keyword Matching) bằng cách ứng dụng Trí tuệ Nhân tạo để hiểu ngữ nghĩa (Semantic Matching).
- **Phạm vi dữ liệu:** 
  - Tập trung vào lĩnh vực Công nghệ thông tin (IT/Tech).
  - Nguồn dữ liệu: Kéo trực tiếp từ HuggingFace Datasets (`lang-uk/recruitment-dataset-job-descriptions-english` và `lang-uk/recruitment-dataset-candidate-profiles-english`).
  - Hỗ trợ đa ngôn ngữ: Hiện tại test bằng tiếng Anh, nhưng đã trang bị sẵn mô hình ngôn ngữ Multilingual, sẵn sàng mở rộng cho dữ liệu Tiếng Việt.

---

## 2. CÔNG NGHỆ SỬ DỤNG (TECH STACK)
- **Backend Framework:** FastAPI (Python) - Đảm nhiệm xây dựng API tốc độ cao.
- **Relational Database:** PostgreSQL - Lưu trữ siêu dữ liệu (Metadata), chức danh, số năm kinh nghiệm, phục vụ các truy vấn lọc cứng (Hard filter) và tìm kiếm Keyword truyền thống.
- **Vector Database:** Milvus - Lưu trữ các Embeddings Vector nhiều chiều và phục vụ tìm kiếm khoảng cách Cosine cực nhanh.
- **Machine Learning / NLP:** 
  - Thư viện: `sentence-transformers`
  - Mô hình Embedding: `paraphrase-multilingual-MiniLM-L12-v2` (Tạo vector 384 chiều).

---

## 3. KIẾN TRÚC HỆ THỐNG VÀ WORKFLOW (ARCHITECTURE & WORKFLOW)

Hệ thống hoạt động dựa trên 2 quy trình chính: Offline (Chuẩn bị dữ liệu) và Online (Tìm kiếm thời gian thực).

### 3.1. Offline Data Pipeline (Chuẩn bị dữ liệu)
- **Thu thập & Làm sạch:** Dữ liệu tải từ HuggingFace dạng thô được làm sạch (loại bỏ khoảng trắng thừa, giới hạn độ dài ký tự bằng hàm `truncate`).
- **Xử lý Missing Data:** Đối mặt với vấn đề dữ liệu thực tế bị khuyết thiếu (Ví dụ: cột `Looking For` thiếu 61.2%, `Highlights` thiếu 58.2%). Hệ thống xử lý linh hoạt bằng cách thay thế giá trị rỗng (`""`) và chỉ ghép nối chuỗi có điều kiện để không làm nhiễu mô hình AI. Cột `Looking For` hoàn toàn bị bỏ qua vì độ nhiễu cao, trong khi `Highlights` được giữ lại vì mang giá trị cộng điểm.
- **Nạp Database Kép (Dual-Ingestion):**
  - Text, vị trí, công ty được Insert vào bảng SQL trong PostgreSQL.
  - Văn bản gộp (`position` + `highlights` + `cv_text`) được chạy qua mô hình AI, biến thành Vector 384 chiều, sau đó Insert vào Milvus Collection.

### 3.2. Online Search Pipeline (Luồng API thời gian thực)
1. **Tiếp nhận:** API `/api/search` nhận câu truy vấn (Ví dụ: *"senior python backend developer"*).
2. **Tiền xử lý (Preprocessing):** Cắt bỏ các "Stop words" (như *the, and, with...*), tách thành danh sách từ khóa cốt lõi `keywords`.
3. **Xử lý song song:** Cùng một lúc, API bắn 2 lệnh tìm kiếm độc lập:
   - **Luồng 1:** Tìm kiếm bằng cấu trúc SQL có trọng số ở PostgreSQL.
   - **Luồng 2:** Tìm kiếm bằng Cosine Similarity ở Milvus, sau đó kết hợp Hybrid Re-ranking.
4. **Phản hồi:** Đóng gói 2 mảng kết quả (SQL Results và Vector Results), thời gian thực thi (time_ms) và chiến thuật nới lỏng trả về cho Frontend UI hiển thị dạng cột song song.

---

## 4. CHI TIẾT CÁC THUẬT TOÁN (ALGORITHMS IN DEPTH)

### 4.1. Nhánh SQL Search (PostgreSQL)
Hệ thống **không sử dụng** tính năng Full-Text Search cài sẵn của Database, mà tự xây dựng một engine riêng biệt gọi là: **Custom Keyword-based Weighted Scoring & Tuning**.

- **Thuật toán Pattern Matching:** Dùng lệnh `ILIKE '%keyword%'` để rà quét sự xuất hiện của từ khóa, không phân biệt hoa thường.
- **Tính điểm Trọng số (Heuristics Weighted Scoring):** Không cào bằng mọi vị trí. Nếu tìm thấy từ khóa:
  - Cột `position` (Chức danh) -> Cộng +2 điểm.
  - Cột `keyword` (Từ khóa chính) -> Cộng +2 điểm.
  - Cột `cv_text` (Nội dung CV) -> Cộng +1 điểm.
  - Cột `highlights` (Điểm nhấn) -> Cộng +1 điểm.
  -> Tổng điểm này gọi là `match_score`.
- **Chiến lược Nới lỏng Tìm kiếm (Fallback / Search Tuning Strategy):** Ngăn chặn tình trạng quá tải hoặc trả về 0 kết quả bằng 3 vòng quét SQL tự động điều chỉnh độ khắt khe:
  - **Vòng AND (Khắt khe):** Tìm ứng viên có CHỨA TOÀN BỘ từ khóa.
  - **Vòng PARTIAL (Trung bình):** Tìm ứng viên chứa >= 2/3 lượng từ khóa.
  - **Vòng OR (Lỏng lẻo):** Tìm ứng viên chứa ít nhất 1 từ khóa.
  -> Vòng quét dừng ngay khi đạt đủ 1000 ứng viên tiềm năng (fetch_limit).
- **Chuẩn hóa %:** Điểm trả về là % kết hợp giữa "Tỷ lệ phủ từ khóa" (Base 70%) và "Thưởng vị trí từ khóa" (Bonus 30%).

### 4.2. Nhánh Vector Search (Milvus)
- **Thuật toán Cosine Similarity:** Mô hình AI chuyển hóa văn bản thành Vector 384 chiều. Milvus tính góc lệch (Cosine) giữa Query Vector và các Candidate Vectors. Góc càng hẹp (điểm càng cao) thì ngữ nghĩa càng giống nhau.
- **Batch SQL Fetching (Tối ưu Hiệu suất):** Milvus chỉ trả về ID và Vector Score (không chứa data dài). Hệ thống gom toàn bộ 1000 ID này, gọi **một câu lệnh SQL duy nhất** (`SELECT ... WHERE id IN (...)`) xuống PostgreSQL để lấy metadata (Kinh nghiệm, Highlights). Việc này ngăn chặn "N+1 Query Problem", giúp hệ thống cực nhẹ và nhanh.
- **Thuật toán Hybrid Re-ranking (Tuyệt chiêu của hệ thống):** Yếu điểm của Vector Search là quá quan tâm ngữ nghĩa mà đôi khi bỏ quên "Từ khóa cứng bắt buộc" (Hard skills keyword). Để vá lỗi này, sau khi lấy điểm Cosine, hệ thống dùng Python quét chuỗi (Lexical matching) để cộng điểm thưởng:
  - Trùng từ khóa trong `Position` -> Thưởng +0.15 vào điểm Vector.
  - Trùng từ khóa trong `Keyword` -> Thưởng +0.10.
  - Trùng từ khóa trong `cv_text` -> Thưởng +0.05.
  -> Điểm cuối cùng (Final Score) kết hợp được cả sức mạnh hiểu **Ngữ nghĩa (AI)** và sự chính xác tuyệt đối của **Từ khóa (Lexical)**.

---

## 5. MỞ RỘNG (FUTURE WORKS / DISCUSSION)
- **Hạn chế hiện tại:** Chưa có Ground-Truth Dataset (danh sách ghép cặp sẵn CV nào phù hợp JD nào do con người chấm) để đo lường tự động độ chính xác (Precision/Recall).
- **Hướng cải thiện:** 
  - Nâng cấp mô hình Embedding chuyên biệt cho IT hơn (như BGE-m3 hoặc all-mpnet-base-v2).
  - Tích hợp thêm AI Multimodal (như CLIP) để quét cả hình ảnh/portfolio đính kèm của ứng viên Designer.
  - Thực hiện Metadata Filtering trực tiếp trên Milvus trước khi Vector Search.
