package com.sia.assistant;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@EnableScheduling
@SpringBootApplication
public class AssistantApplication {

    public static void main(String[] args) {
        // files.delete 가 Desktop.moveToTrash(휴지통 이동)를 쓴다 — headless 면 UnsupportedOperation
        System.setProperty("java.awt.headless", "false");
        SpringApplication app = new SpringApplication(AssistantApplication.class);
        app.setHeadless(false);
        app.run(args);
    }
}
