package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"

	"agrid/auction-realtime/internal/auction"
)

func corsMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		next(w, r)
	}
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8081"
	}

	hub := auction.NewHub()
	go hub.Run()

	mux := http.NewServeMux()

	// 1. Health Check
	mux.HandleFunc("/health", corsMiddleware(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":  "ok",
			"service": "AGR.ID Realtime Auction Service (Golang)",
			"engine":  "Goroutine FIFO Mutex",
		})
	}))

	// 2. WebSocket Endpoint: /ws/auction/{id}
	mux.HandleFunc("/ws/auction/", func(w http.ResponseWriter, r *http.Request) {
		// Parsing ID dari URL: /ws/auction/123
		pathParts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
		if len(pathParts) < 3 {
			http.Error(w, "Invalid auction URL", http.StatusBadRequest)
			return
		}

		eventID, err := strconv.Atoi(pathParts[2])
		if err != nil || eventID <= 0 {
			http.Error(w, "Invalid auction ID", http.StatusBadRequest)
			return
		}

		q := r.URL.Query()
		buyerID, _ := strconv.Atoi(q.Get("buyer_id"))
		buyerName := q.Get("buyer_name")
		if buyerName == "" {
			if buyerID > 0 {
				buyerName = fmt.Sprintf("Peserta #%d", buyerID)
			} else {
				buyerName = "Penonton Tamu"
			}
		}

		conn, err := auction.Upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Printf("Gagal upgrade WebSocket: %v", err)
			return
		}

		client := &auction.Client{
			Hub:       hub,
			Conn:      conn,
			Send:      make(chan []byte, 256),
			EventID:   eventID,
			BuyerID:   buyerID,
			BuyerName: buyerName,
		}

		hub.Register <- client

		go client.WritePump()
		go client.ReadPump()
	})

	// 3. HTTP Bridge Endpoint: POST /api/auction/{id}/bid
	// Memungkinkan Flask / sistem eksisting untuk mem-push bid yang dibuat dari form HTTP
	mux.HandleFunc("/api/auction/", corsMiddleware(func(w http.ResponseWriter, r *http.Request) {
		pathParts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
		// Contoh: api / auction / 12 / bid
		if len(pathParts) < 4 || pathParts[3] != "bid" {
			http.Error(w, "Endpoint not found", http.StatusNotFound)
			return
		}

		eventID, err := strconv.Atoi(pathParts[2])
		if err != nil {
			http.Error(w, "Invalid event ID", http.StatusBadRequest)
			return
		}

		if r.Method == http.MethodPost {
			var body struct {
				BuyerID   int     `json:"buyer_id"`
				BuyerName string  `json:"buyer_name"`
				Nominal   float64 `json:"nominal"`
				Catatan   string  `json:"catatan"`
			}

			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				http.Error(w, "Invalid payload", http.StatusBadRequest)
				return
			}

			room := hub.GetOrCreateRoom(eventID, 0)
			room.IngestExternalBid(body.BuyerID, body.BuyerName, body.Nominal, body.Catatan)

			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]interface{}{
				"success": true,
				"message": "Bid ingested and broadcast successfully",
			})
			return
		}

		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}))

	serverAddr := ":" + port
	log.Printf("==================================================")
	log.Printf(" AGR.ID Realtime Auction Server (Golang)")
	log.Printf(" Listening on http://localhost%s", serverAddr)
	log.Printf(" WebSocket path: ws://localhost%s/ws/auction/{id}", serverAddr)
	log.Printf("==================================================")

	if err := http.ListenAndServe(serverAddr, mux); err != nil {
		log.Fatalf("Server stopped: %v", err)
	}
}
