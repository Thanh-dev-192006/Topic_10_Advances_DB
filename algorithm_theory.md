# Giải mã chi tiết các Thuật toán và Workflow trong Semantic Recruitment Matcher

Tài liệu này giải thích chi tiết toàn bộ "nội công" bên dưới hệ thống của bạn, từ luồng dữ liệu (workflow) cho đến lý thuyết toán học của các thuật toán tìm kiếm. Bạn có thể dùng trực tiếp các kiến thức này để đắp vào **Phần 2 (Cơ sở lý thuyết)** và **Phần 4 (Cài đặt)** trong báo cáo đồ án.

---

## 1. Workflow Tổng thể của Toàn bộ Dự án
Dự án được chia làm 2 giai đoạn chính: **Chuẩn bị Dữ liệu (Data Ingestion)** và **Truy vấn Dữ liệu (Querying)**.

### Giai đoạn 1: Chuẩn bị và Nạp dữ liệu (Offline Pipeline)
1. **Thu thập:** Lấy dữ liệu dạng thô (Raw JDs & CVs) từ HuggingFace Datasets.
2. **Làm sạch (Data Cleaning):** 
   - Xóa bỏ các khoảng trắng thừa.
   - Cắt ngắn văn bản (Truncate) để tránh vượt quá giới hạn token của mô hình AI và giới hạn VARCHAR của Database.
   - Xử lý các giá trị rỗng (Missing Data - ví dụ gán chuỗi rỗng cho `Highlights` hay `Looking For` nếu bị thiếu).
3. **Phân nhánh lưu trữ (Bifurcation):**
   - **Nhánh Relational (PostgreSQL):** Lưu trữ toàn bộ metadata (Text, Kinh nghiệm, Chức danh...) dưới dạng bảng có cấu trúc để phục vụ Keyword Search và hiển thị lên giao diện.
   - **Nhánh Vector (Milvus):** Cắt ghép nội dung (`position` + `highlights` + `cv_text`), đưa qua mô hình AI (Sentence-Transformer) để biến thành **Vector 384 chiều**. Sau đó lưu các Vector này vào Milvus.

### Giai đoạn 2: Tìm kiếm và Trả kết quả (Online Pipeline - `main.py`)
1. Người dùng nhập câu truy vấn (Ví dụ: *"Python backend developer"*).
2. API nhận câu truy vấn, làm sạch (loại bỏ stop words như *and, the, with...*).
3. **Xử lý Song song (Parallel Search):**
   - **Luồng 1 (SQL Search):** Ném các từ khóa vào PostgreSQL để chấm điểm truyền thống.
   - **Luồng 2 (Vector Search):** Ném nguyên câu truy vấn qua mô hình AI để tạo thành *Query Vector*, mang đi rà quét trong Milvus, sau đó kết hợp thêm dữ liệu từ PostgreSQL để chấm điểm lại (Hybrid).
4. Trả về 2 danh sách kết quả (Top 5) lên giao diện để người dùng so sánh.

---

## 2. Các thuật toán áp dụng trong Vector Search (Milvus)

### 2.1. Vector Embedding (Mô hình Sentence-Transformer)
- **Lý thuyết:** Mô hình được dùng là `paraphrase-multilingual-MiniLM-L12-v2`. Bản chất đây là một mạng nơ-ron nhân tạo (Transformer architecture). Khi bạn đưa một câu văn cho nó, nó không nhìn văn bản dưới dạng "chữ", mà nó hiểu ngữ nghĩa của câu và ánh xạ câu đó vào một không gian toán học có **384 chiều**.
- **Cách hoạt động:** Các từ/câu có ý nghĩa giống nhau (ví dụ "Developer" và "Programmer") sẽ được mô hình ném vào các tọa độ nằm rất gần nhau trong không gian 384 chiều này.
- **Vai trò:** Giúp hệ thống thoát khỏi giới hạn của việc so khớp từng chữ cái, cho phép tìm kiếm dựa trên "ý nghĩa" và "ngữ cảnh".

### 2.2. Đo khoảng cách bằng Cosine Similarity
- **Lý thuyết:** Khi truy vấn một câu, hệ thống cũng biến câu truy vấn thành một Vector 384 chiều. Bài toán tìm CV phù hợp nhất trở thành bài toán: *Tìm những Vector CV nằm gần Vector Truy vấn nhất trong không gian 384 chiều.*
- **Công thức:** Milvus sử dụng thuật toán đo góc **Cosine Similarity**. Nó tính góc $\theta$ giữa hai vector. Góc càng hẹp (Cosine tiến về 1) thì hai câu văn càng giống nhau về mặt ngữ nghĩa.
- **Vai trò:** Giúp so khớp cực nhanh hàng triệu CV và đưa ra điểm số Semantic Score (dao động từ 0 đến 1). Điểm số này càng cao nghĩa là CV càng khớp với yêu cầu.

### 2.3. Thuật toán Hybrid Re-ranking (Điểm nhấn của dự án)
- **Cách hoạt động:** Nhược điểm của Vector Search là nó đôi khi quá "bay bổng" theo ngữ nghĩa mà bỏ quên những từ khóa kỹ thuật bắt buộc (như "Python"). Để khắc phục, hệ thống áp dụng kỹ thuật **Lexical Bonus** ngay sau khi Milvus trả về top kết quả.
- **Công thức tính:** 
  `Final_Score = Cosine_Score + Keyword_Bonus`
  Trong đó `Keyword_Bonus` được tính bằng cách: Nếu chữ "Python" có xuất hiện chính xác trong `position` (+0.15 điểm), trong `keyword` (+0.10 điểm), trong `cv_text` (+0.05 điểm).
- **Vai trò:** Đảm bảo kết quả Vector trả về vừa hiểu đúng ngữ nghĩa, vừa không bị rơi rụng các từ khóa "cứng" (Hard skills) cực kỳ quan trọng trong tuyển dụng IT.

---

## 3. Các thuật toán áp dụng trong SQL Search (PostgreSQL)

Nhánh SQL không sử dụng AI, mà sử dụng thuật toán truy vấn chuỗi truyền thống kết hợp với Hệ thống chấm điểm tự thiết kế (**Custom Keyword-based Weighted Scoring**).

### 3.1. Thuật toán Đối sánh Mẫu (Pattern Matching - `ILIKE`)
- **Cách hoạt động:** Sử dụng cấu trúc `ILIKE '%keyword%'` của PostgreSQL. Thuật toán này duyệt qua chuỗi văn bản (Full table scan hoặc thông qua index) để tìm xem chuỗi con (substring) có tồn tại trong chuỗi lớn không, bất kể chữ hoa hay chữ thường.
- **Vai trò:** Bắt chính xác sự tồn tại của từ khóa trong CV. Chống lại điểm yếu của Vector (Vector đôi khi bị "ảo giác" ngữ nghĩa).

### 3.2. Thuật toán Chấm điểm Có Trọng số (Weighted Scoring Heuristic)
- **Lý thuyết:** Không phải chữ "Python" xuất hiện ở đâu cũng có giá trị như nhau. Nếu "Python" nằm ở Chức danh (Position), ứng viên đó xịn hơn rất nhiều so với người chỉ vô tình nhắc chữ "Python" ở cuối đoạn mô tả (cv_text).
- **Cách tính `match_score`:** 
  Hệ thống tính tổng điểm cho từng từ khóa tìm thấy:
  - Nằm ở cột `position` (Chức danh): Trọng số **2**
  - Nằm ở cột `keyword` (Từ khóa chính): Trọng số **2**
  - Nằm ở cột `cv_text` (Nội dung CV): Trọng số **1**
  - Nằm ở cột `highlights` (Kỹ năng nổi bật): Trọng số **1**
- **Chuẩn hóa sang thang 100%:**
  - Lấy 70% số điểm dựa trên Tỷ lệ Phủ từ khóa (Số từ khóa tìm thấy / Tổng số từ khóa truy vấn).
  - Lấy 30% số điểm còn lại dựa trên Trọng số vị trí (Thưởng thêm nếu từ khóa rơi vào các cột xịn như `position`).

### 3.3. Chiến thuật Nới lỏng Ngưỡng (Search Tuning / Fallback Strategy)
- **Vấn đề:** Nếu người dùng gõ 5 từ khóa, bắt SQL tìm CV chứa ĐÚNG CẢ 5 từ khóa (Toán tử AND) thì sẽ ra 0 kết quả. Bắt SQL tìm CV chứa CHỈ 1 từ khóa (Toán tử OR) thì sẽ ra hàng triệu kết quả rác.
- **Cách giải quyết:** Áp dụng thuật toán tìm kiếm thích ứng (Fallback). 
  - Vòng 1: Ép điều kiện `keyword_count = 5` (Phải chứa tất cả).
  - Nếu số kết quả thu được < 1000, chạy tiếp Vòng 2.
  - Vòng 2: Ép điều kiện `keyword_count >= 3` (Chứa khoảng 2/3 từ khóa).
  - Nếu vẫn chưa đủ, chạy Vòng 3.
  - Vòng 3: Bắt điều kiện `keyword_count >= 1` (Có chữ nào cũng được).
- **Vai trò:** Cân bằng hoàn hảo giữa Độ chính xác (Precision) và Độ phủ (Recall), đồng thời ngăn PostgreSQL bị quá tải khi phải tính toán điểm số cho hàng triệu dòng rác.
