package com.clsen.dataweb.production;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

class ProductionError extends RuntimeException {
    final int status;
    final String code;
    ProductionError(int status, String code, String message) { super(message); this.status=status; this.code=code; }
}

@RestControllerAdvice
class ProductionErrorHandler {
    @ExceptionHandler(ProductionError.class)
    ResponseEntity<?> handle(ProductionError error) {
        return ResponseEntity.status(error.status).body(Map.of("error",Map.of("code",error.code,"message",error.getMessage())));
    }
    @ExceptionHandler({org.springframework.dao.DataAccessException.class})
    ResponseEntity<?> database(Exception error) {
        return ResponseEntity.status(503).body(Map.of("error",Map.of("code","production_database_unavailable","message","生产业务存储暂不可用；请查询原操作结果后重试。")));
    }
}
