package com.clsen.dataweb.production;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class ProductionApplication {
    public static void main(String[] args) {
        if (args.length == 1 && args[0].equals("--healthcheck")) {
            try {
                String port=System.getenv().getOrDefault("PRODUCTION_PORT","23011");
                var request=java.net.http.HttpRequest.newBuilder(java.net.URI.create("http://127.0.0.1:"+port+"/internal/production/health"))
                    .timeout(java.time.Duration.ofSeconds(3))
                    .header("Authorization","Bearer "+System.getenv("PRODUCTION_SERVICE_TOKEN"))
                    .header("X-Production-Site","1").header("X-Production-Actor","1").header("X-Production-Roles","viewer").build();
                int status=java.net.http.HttpClient.newHttpClient().send(request,java.net.http.HttpResponse.BodyHandlers.discarding()).statusCode();
                System.exit(status==200?0:1);
            } catch (Exception error) { System.exit(1); }
            return;
        }
        if (args.length == 1 && args[0].equals("--migrate")) {
            org.flywaydb.core.Flyway.configure().dataSource(
                System.getenv("PRODUCTION_DATABASE_URL"), System.getenv("PRODUCTION_MIGRATION_USER"),
                System.getenv("PRODUCTION_MIGRATION_PASSWORD")).load().migrate();
            return;
        }
        if (args.length == 1 && args[0].equals("--serve")) {
            org.flywaydb.core.Flyway.configure().dataSource(
                System.getenv("PRODUCTION_DATABASE_URL"), System.getenv("PRODUCTION_DATABASE_USER"),
                System.getenv("PRODUCTION_DATABASE_PASSWORD")).load().validate();
            args = new String[0];
        }
        SpringApplication.run(ProductionApplication.class, args);
    }
}
