import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../../services/api';
import { FormsModule } from '@angular/forms';


@Component({
  selector: 'app-driver-comparison',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './driver-comparison.html',
  styleUrls: ['./driver-comparison.css']
})
export class DriverComparison implements OnInit {
  drivers: {id: string; name: string}[] = [];
  driver1 = ''; driver2 = '';

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.api.getDrivers().subscribe({
      next: (list) => this.drivers = list,
      error: (err) => console.error('drivers error', err)
    });
  }

  compare(): void {
    console.log('compare', this.driver1, this.driver2);
    // später: API-Call für Vergleich
  }
}
