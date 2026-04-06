# Topic 10: Semantic Recruitment Matcher

Hệ thống tuyển dụng sử dụng công nghệ Vector Search để tìm kiếm ứng viên dựa trên **ngữ nghĩa** thay vì từ khóa cứng.

---

## 📌 Tính Năng Chính

### 1. Tạo Embedding
- Tạo vector embeddings cho **mô tả công việc (JD)** và **hồ sơ ứng viên (CV)**
- Dùng `sentence-transformers` (HuggingFace) để chuyển text/image thành vector (dãy số float)

### 2. Smart Search
- Nhà tuyển dụng mô tả nhu cầu bằng **ngôn ngữ tự nhiên**
- _Ví dụ:_ "cần người có kinh nghiệm làm việc nhóm trong môi trường startup nhanh"
- Hệ thống trả về **top ứng viên phù hợp nhất** dựa trên **vector similarity**
- Không phụ thuộc vào từ khóa cứng

---

## 🎨 Giao Diện Tham Khảo

### Màn Hình "Smart Recruiter"

**Thanh tìm kiếm:**
- Kích thước lớn, dễ nhìn
- Hint text: *"Mô tả bằng cả câu, không cần từ khóa chính xác"*

**Hai cột so sánh:**

| Cột Trái (SQL LIKE) | Cột Phải (Vector Search) |
|---|---|
| Kết quả khớp **từ khóa cứng** | Kết quả theo **ngữ nghĩa** |
| Tìm chính xác | Tìm theo ý nghĩa |

**Hiển thị kết quả:**
- % Match ngữ nghĩa cho mỗi ứng viên
- Highlight các điểm tương đồng chính
- _Ví dụ:_ JD viết "startup agile" → tìm ra CV viết "môi trường linh hoạt, đội nhỏ tốc độ cao"

---

## 🚀 Tính Năng Nâng Cao

### Multimodal Support
- **Upload ảnh portfolio** (cho vị trí Design/Creative)
- Tạo vector từ ảnh + kết hợp với vector text CV
- Tìm kiếm trên **cả hai dạng dữ liệu**

### Vector Database
- **Sử dụng:** `pinecone-client` hoặc `pymilvus`
- **Quy trình:** Text/Image → Vector → Lưu vào DB → Vector Search

---

## 🛠️ Công Nghệ Chính

```
sentence-transformers (HuggingFace) 
    ↓
Chuyển text/image thành vector
    ↓
Lưu vào Vector DB (Pinecone/Milvus)
    ↓
Tính toán similarity & trả kết quả
```

**Thư viện quan trọng:** `sentence-transformers` để chạy AI model tạo vector embeddings