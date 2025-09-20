import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';


@Component({
  selector: 'app-driver-comparison',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './driver-comparison.html',
  styleUrl: './driver-comparison.css'
})
export class DriverComparison {
   drivers = [
    { id: '1', name: 'Max Verstappen' },
    { id: '44', name: 'Lewis Hamilton' },
    { id: '16', name: 'Charles Leclerc' },
    { id: '55', name: 'Carlos Sainz' }
  ];

}
