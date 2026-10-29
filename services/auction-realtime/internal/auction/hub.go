package auction

import (
	"sync"
)

// Hub mengelola semua room lelang yang sedang aktif di sistem AGR.ID
type Hub struct {
	rooms      map[int]*Room
	roomsMutex sync.RWMutex

	Register   chan *Client
	Unregister chan *Client
}

func NewHub() *Hub {
	return &Hub{
		rooms:      make(map[int]*Room),
		Register:   make(chan *Client),
		Unregister: make(chan *Client),
	}
}

func (h *Hub) Run() {
	for {
		select {
		case client := <-h.Register:
			room := h.GetOrCreateRoom(client.EventID, 0)
			room.AddClient(client)

		case client := <-h.Unregister:
			if client.Room != nil {
				client.Room.RemoveClient(client)
			}
		}
	}
}

func (h *Hub) GetOrCreateRoom(eventID int, startingPrice float64) *Room {
	h.roomsMutex.Lock()
	defer h.roomsMutex.Unlock()

	room, exists := h.rooms[eventID]
	if !exists {
		room = NewRoom(eventID, startingPrice)
		h.rooms[eventID] = room
	}
	return room
}

func (h *Hub) GetRoom(eventID int) (*Room, bool) {
	h.roomsMutex.RLock()
	defer h.roomsMutex.RUnlock()

	room, exists := h.rooms[eventID]
	return room, exists
}
