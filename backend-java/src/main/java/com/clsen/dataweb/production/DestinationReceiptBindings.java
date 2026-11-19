package com.clsen.dataweb.production;

import java.util.*;

/** Validates supplied evidence; never infers carton-to-order links. */
final class DestinationReceiptBindings {
    private DestinationReceiptBindings() {}
    record Source(long id, long sku, long units) {}
    record Allocation(long id, long source, long units) {}
    record CartonItem(String carton, long sku, long units) {}
    record Binding(String carton, long source, Long allocation, long sku, long units) {}
    private record CartonSku(String carton, long sku) {}
    private record BindingKey(String carton, long source, Long allocation) {}

    static void validate(List<Source> sources, List<Allocation> allocations,
                         List<CartonItem> cartons, List<Binding> bindings) {
        if (sources.isEmpty() || cartons.isEmpty() || bindings.isEmpty()) invalid();
        Map<Long,Source> sourceById=new HashMap<>();
        Map<Long,Allocation> allocationById=new HashMap<>();
        Map<Long,Long> expectedSources=new HashMap<>(), expectedAllocations=new HashMap<>();
        Map<CartonSku,Long> expectedCartons=new HashMap<>();
        for (var source:sources) {
            if (source.id()<=0 || source.sku()<=0 || source.units()<=0 || sourceById.put(source.id(),source)!=null) invalid();
            expectedSources.put(source.id(),source.units());
        }
        Map<Long,Long> sourceAllocated=new HashMap<>();
        for (var allocation:allocations) {
            if (allocation.id()<=0 || allocation.units()<=0 || !sourceById.containsKey(allocation.source()) || allocationById.put(allocation.id(),allocation)!=null) invalid();
            expectedAllocations.put(allocation.id(),allocation.units());
            add(sourceAllocated,allocation.source(),allocation.units());
        }
        for (var entry:sourceAllocated.entrySet()) if (!entry.getValue().equals(expectedSources.get(entry.getKey()))) invalid();
        for (var item:cartons) {
            if (item.carton()==null || item.carton().isBlank() || item.sku()<=0 || item.units()<=0) invalid();
            if (expectedCartons.put(new CartonSku(item.carton(),item.sku()),item.units())!=null) invalid();
        }
        Map<Long,Long> actualSources=new HashMap<>(), actualAllocations=new HashMap<>();
        Map<CartonSku,Long> actualCartons=new HashMap<>(); Set<BindingKey> seen=new HashSet<>();
        for (var binding:bindings) {
            var source=sourceById.get(binding.source());
            if (source==null || binding.units()<=0 || binding.sku()!=source.sku() || binding.carton()==null || binding.carton().isBlank()) invalid();
            if (!expectedCartons.containsKey(new CartonSku(binding.carton(),binding.sku())) || !seen.add(new BindingKey(binding.carton(),binding.source(),binding.allocation()))) invalid();
            if (binding.allocation()==null) {
                if (sourceAllocated.containsKey(binding.source())) invalid();
            } else {
                var allocation=allocationById.get(binding.allocation());
                if (allocation==null || allocation.source()!=binding.source()) invalid();
                add(actualAllocations,binding.allocation(),binding.units());
            }
            add(actualSources,binding.source(),binding.units());
            add(actualCartons,new CartonSku(binding.carton(),binding.sku()),binding.units());
        }
        if (!expectedSources.equals(actualSources) || !expectedAllocations.equals(actualAllocations) || !expectedCartons.equals(actualCartons)) invalid();
    }
    private static <T> void add(Map<T,Long> totals,T key,long units) {
        try { totals.merge(key,units,Math::addExact); }
        catch (ArithmeticException ex) { invalid(); }
    }
    private static void invalid() {
        throw new ProductionError(422,"shipment_binding_invalid","箱、来源和订单分配的数量或身份不一致，请保留输入并逐项核对。");
    }
}
