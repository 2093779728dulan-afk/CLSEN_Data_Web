package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;

class OrderTablePreviewTest {
    @Test void sourcePreviewKeepsOriginalBytesAndCannotConfirmSourceProblems() throws Exception {
        var db=mock(JdbcTemplate.class);var service=mock(ProductionService.class);var json=new ObjectMapper();
        var files=new ProductionFiles(db,service,json);
        when(db.queryForObject(anyString(),eq(Long.class),anyLong(),anyLong())).thenReturn(1L);
        when(db.queryForObject(anyString(),eq(Long.class),anyLong(),anyLong(),anyLong())).thenReturn(1L);
        when(service.checkSource(any(),eq("orders"),any())).thenReturn(Map.of("candidates",List.of()));
        var original="unchanged original source attachment".getBytes(StandardCharsets.UTF_8);
        byte[] canonical;
        try(var book=new XSSFWorkbook(new ByteArrayInputStream(files.template("orders")));var output=new ByteArrayOutputStream()) {
            var row=book.getSheetAt(0).createRow(1);
            var values=List.of("","2026-10-30","QA-Exact-M","7","");
            for(int i=0;i<values.size();i++)row.createCell(i).setCellValue(values.get(i));
            book.write(output);canonical=output.toByteArray();
        }
        var input=new LinkedHashMap<String,Object>();
        input.put("file_base64",Base64.getEncoder().encodeToString(canonical));
        input.put("_original_file_base64",Base64.getEncoder().encodeToString(original));
        input.put("filename","original.xlsx");input.put("mode","create");input.put("workbench_order",true);
        input.put("factory_id","3");input.put("receipt_warehouse_id","1");input.put("receipt_owner_id","1");
        var identity=Map.of("sku_id","9","label","QA exact","status","active","catalog_version","qa:1");
        input.put("_catalog",Map.of("9",identity));input.put("_resolved_codes",Map.of("QA-Exact-M",identity));
        input.put("_order_source",Map.of("sheet","November","rows",List.of(Map.of("source_row",9)),"issues",List.of(Map.of("row",9,"message","source style differs"))));
        var result=json.valueToTree(files.preview(new ProductionContext(1,4,Set.of("admin")),"orders",json.valueToTree(input)));
        assertEquals("draft",result.path("command").path("save_mode").asText());
        assertEquals("order-table-v4",result.path("template_version").asText());
        assertEquals("source style differs",result.path("issues").get(0).path("message").asText());
        assertEquals(9,result.path("command").path("_source_table").path("rows").get(0).path("source_row").asInt());
        assertEquals(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(original)),result.path("digest").asText());
        var write=mockingDetails(db).getInvocations().stream().filter(i->i.getMethod().getName().equals("update")).findFirst().orElseThrow();
        assertArrayEquals(original,write.getArgument(7,byte[].class));
        verify(service,never()).command(any(),anyString(),any(),anyString(),anyString(),any());
        // Unknown codes keep their physical source row and block confirmation as before.
        input.put("_resolved_codes",Map.of());
        var unknown=json.valueToTree(files.preview(new ProductionContext(1,4,Set.of("admin")),"orders",json.valueToTree(input)));
        assertEquals(9,unknown.path("issues").get(0).path("row").asInt());
        assertTrue(unknown.path("rows").isEmpty());
    }
}
