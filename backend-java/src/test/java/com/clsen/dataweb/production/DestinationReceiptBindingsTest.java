package com.clsen.dataweb.production;
import static org.junit.jupiter.api.Assertions.*;
import java.util.List;
import org.junit.jupiter.api.Test;
import static com.clsen.dataweb.production.DestinationReceiptBindings.*;

class DestinationReceiptBindingsTest {
    @Test void tracesSameSkuAcrossTwoOrdersAndCartonsWithoutGuessing() {
        var sources=List.of(new Source(1, 7, 60), new Source(2, 7, 40));
        var allocations=List.of(new Allocation(11, 1, 60), new Allocation(22, 2, 40));
        var cartons=List.of(new CartonItem("box-a", 7, 50),new CartonItem("box-b", 7, 50));
        var bindings=List.of(new Binding("box-a",1,11L,7,50),new Binding("box-b",1,11L,7,10),new Binding("box-b",2,22L,7,40));
        assertDoesNotThrow(() -> validate(sources,allocations,cartons,bindings));
        assertThrows(ProductionError.class, () -> validate(sources,allocations,cartons,bindings.subList(0,2)));
        assertThrows(ProductionError.class, () -> validate(sources,allocations,cartons,List.of(new Binding("box-a",1,22L,7,50))));
    }
    @Test void directSourceHasExplicitNullAllocationAndCannotBorrowAnotherSource() {
        var sources=List.of(new Source(1, 7, 5));
        var boxes=List.of(new CartonItem("box-a",7,5));
        assertDoesNotThrow(() -> validate(sources,List.of(),boxes,List.of(new Binding("box-a",1,null,7,5))));
        assertThrows(ProductionError.class, () -> validate(sources,List.of(),boxes,List.of(new Binding("box-a",1,99L,7,5))));
        assertThrows(ProductionError.class, () -> validate(sources,List.of(),boxes,List.of(new Binding("box-a",1,null,8,5))));
    }
}
